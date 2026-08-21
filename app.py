# -*- coding: utf-8 -*-
"""
app.py —— 通用票据/文档提取服务  v7
流程：同类票据上传 → 三态判定 → AI 推荐字段(或预设) → 单页合并提取(并发)
      → 续页感知合并 → 本地算术校验 → 不一致自动复核一轮 → 结果/Excel
      异构文档另走快速分拣：分类 → 边界校正 → 按类型保存 PDF/ZIP，之后分别上传提取。

相对旧版的关键改动：
  · 全部文件的页摊平进同一对线程池（文本高并发/视觉限流），
    多文件不再串行——批量小文件的总时长约等于最慢一页。
  · 结果按 job_id 隔离，多人同时用互不覆盖（旧版全局 _last 会串台）。
  · 中文文件名原样保留（旧版 secure_filename 会把中文剥光导致同名串档）。
  · sum_check 不一致的记录自动触发一轮复核：原始页重渲更高清图 +
    「差额提示」重新提取，修复后重合并；仍不一致才标红交人工。
  · /api/ping 一键测网关连通与视觉能力，内网排障不再靠猜。
"""
import io
import os
import re
import json
import time
import uuid
import queue
import logging
import threading
import traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import (Flask, render_template, request, jsonify, Response,
                   send_file, make_response)

import pdf_utils as P
import presets as PS
from ai_client import GatewayConfig, AIClient, AIResponseError, robust_call, parse_json
from extractor import extract_page, repair_note_for
from merge import normalize_fields, merge_pages, splice_results
from excel_export import write_excel
import common_mode as CM
import mixed_mode as MM
import split_mode as SM
from common_export import write_common_excel, write_mixed_excel

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger('app')

DEFAULT_API_URL = os.environ.get('ANTHROPIC_BASE_URL', '')
DEFAULT_TOKEN = os.environ.get('ANTHROPIC_AUTH_TOKEN', '')
# 覆盖环境变量（留空则在前端手动填入）
os.environ['ANTHROPIC_BASE_URL'] = ''
os.environ['ANTHROPIC_AUTH_TOKEN'] = ''
DEFAULT_MODEL = os.environ.get('CLAUDE_MODEL', '')
TEXT_WORKERS = int(os.environ.get('TEXT_WORKERS', '8'))
VISION_WORKERS = int(os.environ.get('VISION_WORKERS', '3'))
REPAIR_MAX = int(os.environ.get('REPAIR_MAX', '6'))       # 每次任务最多自动复核的记录数
ANALYZE_IMG_SIDE = int(os.environ.get('ANALYZE_IMG_SIDE', '1600'))
REPAIR_IMG_SIDE = int(os.environ.get('REPAIR_IMG_SIDE', '2400'))
SPLIT_ROOT = os.environ.get(
    'SPLIT_ROOT', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results', 'split'))
FAST_SPLIT_TEXT_WORKERS = int(os.environ.get(
    'FAST_SPLIT_TEXT_WORKERS', str(max(1, min(3, TEXT_WORKERS)))))
FAST_SPLIT_VISION_WORKERS = int(os.environ.get(
    'FAST_SPLIT_VISION_WORKERS', str(max(1, min(2, VISION_WORKERS)))))

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# ── 任务存储（内存，保留最近 20 个 / 2 小时）────────────────────
JOBS = OrderedDict()
_JOBS_LOCK = threading.Lock()

# 测试注入：替换成 (kind, system, user, max_tokens, image_b64=None)->(text,stop) 即可
_AI_CALL_OVERRIDE = None


def _make_ai_call(cfg):
    if _AI_CALL_OVERRIDE is not None:
        return _AI_CALL_OVERRIDE
    return AIClient(cfg).call


def _cfg_from(req):
    src = req.form if req.form else (req.json if req.is_json else {})
    return GatewayConfig(src.get('api_url') or DEFAULT_API_URL,
                         src.get('api_key') or DEFAULT_TOKEN,
                         src.get('model') or DEFAULT_MODEL)


def _store_job(job_id, payload):
    with _JOBS_LOCK:
        JOBS[job_id] = payload
        JOBS[job_id]['ts'] = time.time()
        while len(JOBS) > 20:
            JOBS.popitem(last=False)
        cutoff = time.time() - 7200
        for k in [k for k, v in JOBS.items() if v['ts'] < cutoff]:
            JOBS.pop(k, None)


def safe_name(n):
    """保留中文，只清路径分隔与控制字符；旧版 secure_filename 会把中文剥空导致串档。"""
    n = os.path.basename(str(n or ''))
    n = re.sub(r'[\\/\x00-\x1f\x7f]', '_', n).strip() or 'file.pdf'
    return n[:120]


def _uniq_names(names):
    seen, out = {}, []
    for n in names:
        if n not in seen:
            seen[n] = 0
            out.append(n)
        else:
            seen[n] += 1
            stem, dot, ext = n.rpartition('.')
            out.append('%s(%d).%s' % (stem, seen[n], ext) if dot else
                       '%s(%d)' % (n, seen[n]))
    return out


def _sse(o):
    return 'data: ' + json.dumps(o, ensure_ascii=False) + '\n\n'


# ══════════════════════════════════════════════════════════════
#  页面 & 预设
# ══════════════════════════════════════════════════════════════
@app.route('/')
def index():
    r = make_response(render_template('index.html', default_model=DEFAULT_MODEL,
                                      presets=list(PS.PRESETS.keys())))
    r.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return r


@app.route('/api/preset/<name>')
def api_preset(name):
    return jsonify(PS.PRESETS.get(name, []))


# ══════════════════════════════════════════════════════════════
#  连通性 / 能力探测
# ══════════════════════════════════════════════════════════════
_TINY_PNG_JPEG = None


def _tiny_probe_image():
    global _TINY_PNG_JPEG
    if _TINY_PNG_JPEG is None:
        from PIL import Image
        img = Image.new('RGB', (64, 64), 'white')
        _TINY_PNG_JPEG = P.pil_to_b64(img, max_side=64, quality=80)
    return _TINY_PNG_JPEG


@app.route('/api/ping', methods=['POST'])
def api_ping():
    cfg = _cfg_from(request)
    out = {'gateway': cfg.base_url, 'model': cfg.model,
           'ocr': P.ocr_available()}
    ai = _make_ai_call(cfg)
    if isinstance(ai, AIClient):
        out['proxy_bypass'] = not ai._trust_env_proxy()
    t0 = time.time()
    try:
        text, _ = ai('text', '你是回显器。', '只回复两个字：OK', 12800000)
        out['text_ok'] = True
        out['text_ms'] = int((time.time() - t0) * 1000)
        out['echo'] = (text or '')[:40]
    except Exception as e:
        out['text_ok'] = False
        out['error'] = '%s: %s' % (type(e).__name__, str(e)[:300])
        return jsonify(out)
    t1 = time.time()
    try:
        ai('vision', '你是回显器。', '这是一张纯白测试图。只回复两个字：OK', 12800000,
           image_b64=_tiny_probe_image())
        out['vision_ok'] = True
        out['vision_ms'] = int((time.time() - t1) * 1000)
    except AIResponseError as e:
        out['vision_ok'] = False
        out['vision_error'] = str(e)[:300]
    except Exception as e:
        out['vision_ok'] = False
        out['vision_error'] = '%s: %s' % (type(e).__name__, str(e)[:300])
    return jsonify(out)


# ══════════════════════════════════════════════════════════════
#  AI-1 分析：推荐字段
# ══════════════════════════════════════════════════════════════
@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    cfg = _cfg_from(request)
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400
    fb = request.files['file'].read()
    if not fb:
        return jsonify({'error': '文件为空'}), 400
    fname = safe_name(request.files['file'].filename)
    try:
        pf = P.open_file(fname, fb).scan()
    except Exception as e:
        return jsonify({'error': '无法打开 PDF/图片：%s' % e}), 400
    kinds = [pg.kind for pg in pf.pages]
    summary = {'total': len(kinds), 'native': kinds.count('native'),
               'scanned': kinds.count('scanned'), 'blank': kinds.count('blank')}
    pages_note = '共%d页：电子%d/扫描%d/空白%d' % (
        summary['total'], summary['native'], summary['scanned'], summary['blank'])
    ai = _make_ai_call(cfg)
    try:
        native_idx = [i for i, k in enumerate(kinds) if k == 'native'][:3]
        if native_idx:
            budget, chunks = 7000, []
            for i in native_idx:
                t = pf.pages[i].text
                if not t:
                    continue
                take = t[:max(0, budget)]
                if take:
                    chunks.append('── 第%d页 ──\n%s' % (i + 1, take))
                    budget -= len(take)
            user = PS.analyze_user(True, '\n\n'.join(chunks), pages_note)
            raw = _ask_analyze(ai, 'text', user, None)
        else:
            first_scan = next((i for i, k in enumerate(kinds) if k == 'scanned'), None)
            if first_scan is None:
                return jsonify({'error': '整份文件都是空白页'}), 400
            img = pf.render(first_scan, target_side=ANALYZE_IMG_SIDE)
            b64 = P.pil_to_b64(img, max_side=ANALYZE_IMG_SIDE, quality=85)
            hint = P.ocr_layout(img) or pf.pages[first_scan].hint
            user = PS.analyze_user(False, hint, pages_note)
            raw = _ask_analyze(ai, 'vision', user, b64)
        data = parse_json(raw)
        fields = normalize_fields(data.get('fields') or [])
        if not fields:
            snippet = (raw or '').strip()[:160] or '(空)'
            return jsonify({'doc_type': '(AI 未给出可用字段，已回退默认模板)',
                            'fields': normalize_fields(PS.DEFAULT_FIELDS),
                            'pages': summary,
                            'warning': 'AI 原始回复：“%s”' % snippet})
        return jsonify({'doc_type': data.get('doc_type', ''), 'fields': fields,
                        'pages': summary})
    except Exception as e:
        logger.warning('分析失败: %s', traceback.format_exc())
        return jsonify({'doc_type': '(自动分析失败，已回退默认模板)',
                        'fields': normalize_fields(PS.DEFAULT_FIELDS),
                        'pages': summary, 'warning': str(e)[:300]})
    finally:
        pf.close()


def _ask_analyze(ai, kind, user, image_b64):
    def once(u):
        t, _ = robust_call(lambda: ai(kind, PS.ANALYZE_SYSTEM, u, 12800000,
                                      image_b64=image_b64), ctx='[分析] ')
        return t
    raw = once(user)
    try:
        parse_json(raw)
        return raw
    except ValueError:
        return once(user + '\n\n（你上一次的输出无法解析为 JSON。请只输出 JSON 对象。）')


# ══════════════════════════════════════════════════════════════
#  异构票据：AI 观察代表页并归纳统一字段（独立于原有同类票据流程）
# ══════════════════════════════════════════════════════════════
@app.route('/api/common/analyze', methods=['POST'])
def api_common_analyze():
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': '没有上传文件'}), 400
    names = _uniq_names([safe_name(f.filename) for f in files])
    loaded = [(n, f.read()) for n, f in zip(names, files)]
    cfg = _cfg_from(request)
    pfs = []
    try:
        pfs, bad_pairs = _scan_common_loaded(loaded)
        bad = [{'filename': name, 'error': error[:180]} for name, error in bad_pairs]
        if not pfs:
            return jsonify({'error': '没有可解析的 PDF 或图片', 'bad_files': bad}), 400
        result, refs = _discover_common_from_pfs(pfs, cfg)
        if not result['fields']:
            return jsonify({'error': 'AI 未归纳出可用的公共字段'}), 422
        kinds = [page.kind for pf in pfs for page in pf.pages]
        return jsonify({
            'summary': result['summary'], 'document_types': result['document_types'],
            'fields': result['fields'], 'sampled_pages': len(refs),
            'pages': {'total': len(kinds), 'native': kinds.count('native'),
                      'scanned': kinds.count('scanned'), 'blank': kinds.count('blank')},
            'files': len(pfs), 'bad_files': bad,
        })
    except Exception as e:
        logger.warning('公共字段分析失败: %s', traceback.format_exc())
        return jsonify({'error': '公共字段分析失败：%s' % str(e)[:300]}), 500
    finally:
        for pf in pfs:
            pf.close()


def _scan_common_loaded(loaded):
    pfs, bad = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(lambda nb: P.open_file(nb[0], nb[1]).scan(), nb): nb[0]
                for nb in loaded}
        for fut, name in futs.items():
            try:
                pfs.append(fut.result())
            except Exception as e:
                bad.append((name, str(e)))
    order = [name for name, _ in loaded]
    pfs.sort(key=lambda pf: order.index(pf.name))
    return pfs, bad


def _split_page_item(pf, idx, item):
    """把分拣模型的结果补成保存器需要的页级对象。"""
    item = dict(item or {})
    item.update({'_filename': pf.name, '_page': idx + 1, '_kind': pf.pages[idx].kind,
                 '_source_pf': pf, '_source_idx': idx})
    return item


def _fast_split_loaded(loaded, cfg, emit):
    """快速分拣主流程：扫描 → 批量分类 → 本地边界校正 → 按类型保存。

    这里故意不做字段观察、字段建模或字段提取。异构文件先变成多个可下载的
    同类 PDF，用户再把每个分组送入原有的精准/跨版式流程，避免不同业务字段
    被强行压进一张结果表。
    """
    pfs, bad = _scan_common_loaded(loaded)
    if not pfs:
        raise ValueError('没有可解析的 PDF 或图片')
    total_pages = sum(pf.page_count for pf in pfs)
    blank_pages = sum(page.kind == 'blank' for pf in pfs for page in pf.pages)
    emit({'type': 'start', 'mode': 'split', 'total_pages': total_pages,
          'files': len(pfs), 'blank_pages': blank_pages, 'ocr': P.ocr_available()})
    for name, error in bad or []:
        emit({'type': 'page', 'mode': 'error', 'filename': name, 'page': 0,
              'current': 0, 'total_pages': total_pages,
              'error': '无法打开: %s' % str(error)[:180]})

    ai = _make_ai_call(cfg)
    pages, futures, pools = [], {}, []

    # 电子 PDF：一份来源文件按 18 页左右批量请求，减少请求数；同一文件内仍按页保序。
    native_files = [(pf, [i for i, page in enumerate(pf.pages) if page.kind == 'native'])
                    for pf in pfs]
    native_files = [(pf, indices) for pf, indices in native_files if indices]

    def classify_native_file(pf, indices):
        items = SM.classify_native_batches(
            ai, pf, indices,
            emit=lambda event: emit(dict(event, mode='split')),
            ctx='[快速分拣文本 %s] ' % pf.name)
        by_page = {int(item.get('page', 0)): item for item in items}
        return [_split_page_item(pf, idx, by_page.get(idx + 1, SM._fallback_item(pf, idx)))
                for idx in indices]

    if native_files:
        pool = ThreadPoolExecutor(max_workers=max(1, min(FAST_SPLIT_TEXT_WORKERS,
                                                          len(native_files))))
        pools.append(pool)
        for pf, indices in native_files:
            futures[pool.submit(classify_native_file, pf, indices)] = ('native', pf, indices)

    # 扫描页：本地 OCR 有结果时只发文字；没有 OCR 才发单页图片，减少视觉请求。
    scanned_tasks = [(pf, i) for pf in pfs for i, page in enumerate(pf.pages)
                     if page.kind == 'scanned']

    def classify_scanned(pf, idx):
        page = pf.pages[idx]
        image_b64, ocr_hint = None, ''
        try:
            image = pf.render(idx, target_side=ANALYZE_IMG_SIDE)
            ocr_hint = P.ocr_layout(image) or page.hint
            if not ocr_hint:
                image_b64 = P.pil_to_b64(image, max_side=ANALYZE_IMG_SIDE, quality=82)
            raw = SM.classify_scanned_page(
                ai, pf, idx, image_b64=image_b64, ocr_hint=ocr_hint,
                ctx='[快速分拣扫描 %s] ' % pf.name)
            item = SM._normalize_items(raw, pf, [idx])[0]
        except Exception as exc:
            item = SM._fallback_item(pf, idx)
            item['reason'] = '扫描页分拣失败：%s' % str(exc)[:90]
            item['_error'] = '%s: %s' % (type(exc).__name__, str(exc)[:220])
        return _split_page_item(pf, idx, item)

    if scanned_tasks:
        pool = ThreadPoolExecutor(max_workers=max(1, min(FAST_SPLIT_VISION_WORKERS,
                                                          len(scanned_tasks))))
        pools.append(pool)
        for pf, idx in scanned_tasks:
            futures[pool.submit(classify_scanned, pf, idx)] = ('scanned', pf, [idx])

    # 空白页不调用 AI，但保留在页数统计中，不进入任何输出分组。
    for pf in pfs:
        for idx, page in enumerate(pf.pages):
            if page.kind == 'blank':
                pages.append({'_filename': pf.name, '_page': idx + 1, '_kind': 'blank',
                              '_blank': True, '_source_pf': pf, '_source_idx': idx})

    finished = 0
    try:
        for future in as_completed(futures):
            kind, pf, _indices = futures[future]
            result = future.result()
            pages.extend(result if isinstance(result, list) else [result])
            finished += len(result) if isinstance(result, list) else 1
            emit({'type': 'progress', 'mode': 'split',
                  'message': '快速分类 %d/%d 页…' % (finished, max(1, total_pages - blank_pages)),
                  'pct': 42 + int(42 * finished / max(1, total_pages - blank_pages))})
    finally:
        for pool in pools:
            pool.shutdown(wait=True)

    pages = SM.apply_layout_fallback(pages)
    fallback_pages = sum(1 for page in pages if page.get('_layout_fallback'))
    if fallback_pages:
        emit({'type': 'progress', 'mode': 'split',
              'message': 'AI分类未覆盖部分页面，已按标题和版式证据兜底拆分 %d 页…' % fallback_pages,
              'pct': 84})
    pages = SM.split_different_formats(pages)
    pages = SM.apply_local_boundaries(pages)
    groups = SM.type_groups(pages)
    if not groups:
        raise ValueError('上传内容全部为空白页，无法生成分组文件')
    emit({'type': 'progress', 'mode': 'split', 'message': '正在保存分类 PDF…', 'pct': 88})
    job_id = uuid.uuid4().hex[:12]
    root_dir = os.path.join(SPLIT_ROOT, job_id)
    try:
        saved, metadata = SM.save_type_files(groups, pfs, job_id, root_dir)
    finally:
        for pf in pfs:
            pf.close()

    stored_groups = []
    public_groups = []
    for group in saved:
        stored = {k: group.get(k) for k in (
            'key', 'document_type', 'file_name', 'file_path', 'page_count',
            'logical_documents', 'fallback_pages', 'source_files', 'document_segments')}
        stored_groups.append(stored)
        public = {k: stored.get(k) for k in stored if k != 'file_path'}
        public['download_url'] = '/mixed/download?job=%s&type=%s' % (
            job_id, group.get('key', ''))
        public_groups.append(public)
    public_metadata = {'job': job_id, 'groups': public_groups}
    _store_job(job_id, {'mode': 'split', 'groups': stored_groups,
                        'metadata': public_metadata, 'split_dir': root_dir})
    emit({'type': 'result', 'mode': 'split', 'job': job_id,
          'total_pages': total_pages, 'blank_pages': blank_pages,
          'files': len(pfs), 'groups': public_groups,
          'fallback_pages': fallback_pages,
          'classification_warning': ('部分页面未得到 AI 分类，已按标题和版式证据拆分；请核对分类名称。'
                                      if fallback_pages else ''),
          'bad_files': [{'filename': n, 'error': str(e)[:180]} for n, e in bad],
          'download_url': '/download?job=%s' % job_id})


def _discover_common_from_pfs(pfs, cfg, emit=None):
    refs = CM.representative_pages(pfs)
    if not refs:
        raise ValueError('上传文件中没有可分析的页面')
    ai = _make_ai_call(cfg)
    caps, inventories = {'vision': True}, []
    for pos, (pf, idx) in enumerate(refs, 1):
        page = pf.pages[idx]
        image_b64, ocr_hint = None, ''
        if page.kind != 'native':
            img = pf.render(idx, target_side=ANALYZE_IMG_SIDE)
            image_b64 = P.pil_to_b64(img, max_side=ANALYZE_IMG_SIDE, quality=85)
            ocr_hint = P.ocr_layout(img) or page.hint
        item = CM.observe_page(
            ai, kind=page.kind, fname=pf.name, page_no=idx + 1,
            total=pf.page_count, text=page.text or page.hint,
            image_b64=image_b64, ocr_hint=ocr_hint, caps=caps,
            ctx='[公共字段观察 %s p%d] ' % (pf.name, idx + 1))
        item['_source'] = {'filename': pf.name, 'page': idx + 1}
        inventories.append(item)
        if emit:
            emit({'type': 'progress',
                  'message': 'AI 观察差异化代表页 %d/%d…' % (pos, len(refs)),
                  'pct': 5 + int(25 * pos / len(refs))})
    if emit:
        emit({'type': 'progress', 'message': '分批归纳并合并公共字段…', 'pct': 32})
    return CM.discover_from_inventories(ai, inventories), refs


def _observe_mixed_loaded(loaded, cfg, emit=None):
    """混合模式：观察全部非空页面，再做边界复核和按类型字段建模。"""
    pfs, bad = _scan_common_loaded(loaded)
    if not pfs:
        raise ValueError('没有可解析的 PDF 或图片')
    ai = _make_ai_call(cfg)
    caps = {'vision': True}
    tasks = [(pf, idx) for pf in pfs for idx in range(pf.page_count)]
    pages, lock = [], threading.Lock()

    def observe_one(pf, idx):
        page = pf.pages[idx]
        if page.kind == 'blank':
            return {'_filename': pf.name, '_page': idx + 1, '_blank': True,
                    '_kind': 'blank', '_source_pf': pf, '_source_idx': idx}
        try:
            image_b64, ocr_hint = None, ''
            if page.kind != 'native':
                image = pf.render(idx, target_side=ANALYZE_IMG_SIDE)
                image_b64 = P.pil_to_b64(image, max_side=ANALYZE_IMG_SIDE, quality=85)
                ocr_hint = P.ocr_layout(image) or page.hint
            item = CM.observe_page(
                ai, kind=page.kind, fname=pf.name, page_no=idx + 1,
                total=pf.page_count, text=page.text or page.hint,
                image_b64=image_b64, ocr_hint=ocr_hint, caps=caps,
                ctx='[混合文档观察 %s p%d] ' % (pf.name, idx + 1))
            return MM.page_from_inventory(
                item, filename=pf.name, page_no=idx + 1, kind=page.kind,
                pf=pf, idx=idx)
        except Exception as e:
            return {'_filename': pf.name, '_page': idx + 1, '_kind': page.kind,
                    '_error': '%s: %s' % (type(e).__name__, str(e)[:220]),
                    '_source_pf': pf, '_source_idx': idx}

    text_tasks = [(pf, i) for pf, i in tasks if pf.pages[i].kind == 'native']
    vision_tasks = [(pf, i) for pf, i in tasks if pf.pages[i].kind == 'scanned']
    pools = []
    if text_tasks:
        pools.append((ThreadPoolExecutor(max_workers=max(1, min(TEXT_WORKERS, len(text_tasks)))),
                      text_tasks))
    if vision_tasks:
        pools.append((ThreadPoolExecutor(max_workers=max(1, min(VISION_WORKERS, len(vision_tasks)))),
                      vision_tasks))
    futures = []
    for pool, work in pools:
        futures.extend(pool.submit(observe_one, pf, idx) for pf, idx in work)
    finished = 0
    for future in as_completed(futures):
        pages.append(future.result())
        finished += 1
        if emit:
            emit({'type': 'progress', 'message': 'AI识别混合文档页面 %d/%d…' %
                  (finished, len(tasks)), 'pct': 5 + int(35 * finished / max(1, len(tasks)))})
    for pool, _work in pools:
        pool.shutdown()
    # 空白页不需要调用 AI，但要保留在页级清单里，让前端进度和结果页数与实际上传内容一致。
    pages.extend(observe_one(pf, idx) for pf, idx in tasks
                 if pf.pages[idx].kind == 'blank')
    pages.sort(key=lambda p: (str(p.get('_filename', '')), int(p.get('_page', 0))))
    segment_issues = CM.refine_document_boundaries(
        ai, pages, [], ctx='[混合文档边界复核] ')
    if emit:
        emit({'type': 'progress', 'message': '按文档类型分别总结字段…', 'pct': 45})
    schemas = MM.discover_type_schemas(ai, pages, ctx='[混合文档字段总结] ')
    return pfs, bad, pages, schemas, segment_issues, ai


def _mixed_schema_json(schemas):
    return [{'document_type': s.get('document_type', '未知'),
             'summary': s.get('summary', ''),
             'sampled_pages': s.get('sampled_pages', 0),
             'fields': s.get('fields', [])} for s in schemas]


@app.route('/api/mixed/analyze', methods=['POST'])
def api_mixed_analyze():
    """旧客户端兼容接口；新界面使用 /mixed/split，先保存分组文件再分别提取。"""
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': '没有上传文件'}), 400
    names = _uniq_names([safe_name(f.filename) for f in files])
    loaded = [(n, f.read()) for n, f in zip(names, files)]
    pfs = []
    try:
        pfs, bad, pages, schemas, segment_issues, _ai = _observe_mixed_loaded(
            loaded, _cfg_from(request))
        nonblank = [p for p in pages if not p.get('_blank')]
        anchors = {(p.get('_filename'), p.get('_segment_anchor') or p.get('_page'))
                   for p in nonblank}
        return jsonify({
            'mode': 'mixed', 'schemas': _mixed_schema_json(schemas),
            'document_types': [s.get('document_type') for s in schemas],
            'logical_documents': len(anchors), 'boundary_issues': segment_issues,
            'pages': {'total': sum(len(pf.pages) for pf in pfs),
                      'native': sum(x.kind == 'native' for pf in pfs for x in pf.pages),
                      'scanned': sum(x.kind == 'scanned' for pf in pfs for x in pf.pages),
                      'blank': sum(x.kind == 'blank' for pf in pfs for x in pf.pages)},
            'files': len(pfs),
            'bad_files': [{'filename': n, 'error': e[:180]} for n, e in bad],
        })
    except Exception as e:
        logger.warning('混合文档分析失败: %s', traceback.format_exc())
        return jsonify({'error': '混合文档分析失败：%s' % str(e)[:300]}), 500
    finally:
        for pf in pfs:
            pf.close()


def _run_mixed_extraction(job_id, loaded, pfs, bad, pages, schemas,
                          segment_issues, ai, cfg, emit):
    """按已确认的逻辑文档类型分别调用字段方案。"""
    caps = {'vision': True}
    tasks = [p for p in pages]
    total = len(tasks)
    emit({'type': 'start', 'mode': 'mixed', 'total_pages': total,
          'files': len(pfs), 'blank_pages': sum(p.get('_blank', False) for p in pages),
          'ocr': P.ocr_available(), 'job': job_id})
    results, done, lock = [], [0], threading.Lock()
    for name, error in bad or []:
        emit({'type': 'page', 'mode': 'error', 'filename': name, 'page': 0,
              'current': done[0], 'total_pages': total,
              'error': '无法打开: %s' % str(error)[:180]})

    def run_page(page):
        if page.get('_blank'):
            return page
        if page.get('_error'):
            return page
        schema = MM.schema_for(schemas, page.get('_document_type'))
        if not schema or not schema.get('fields'):
            page['_error'] = 'AI 未为文档类型《%s》生成字段方案' % page.get('_document_type', '未知')
            return page
        pf, idx = page.get('_source_pf'), page.get('_source_idx')
        kind = page.get('_kind') or 'native'
        ctx = '[混合文档提取 %s p%d] ' % (page.get('_filename'), page.get('_page'))
        try:
            if kind == 'native':
                data = CM.common_extract_page(
                    schema['fields'], ai, kind='native', fname=pf.name,
                    page_no=idx + 1, total=pf.page_count,
                    text=pf.pages[idx].text, caps=caps,
                    document_types=[schema.get('document_type')], ctx=ctx)
            else:
                img = pf.render(idx)
                data = CM.common_extract_page(
                    schema['fields'], ai, kind='scanned', fname=pf.name,
                    page_no=idx + 1, total=pf.page_count, text=pf.pages[idx].hint,
                    image_b64=P.pil_to_b64(img), ocr_hint=P.ocr_layout(img),
                    caps=caps, document_types=[schema.get('document_type')], ctx=ctx)
            # 边界阶段已经看过全页，提取阶段不得自行改类型或拆分结果。
            for key in ('_document_type', '_document_no', '_segment_anchor',
                        '_segment_confidence', '_segment_reason', '_page_role',
                        '_is_continuation', '_page_summary', '_identity_hints'):
                if key in page:
                    data[key] = page[key]
            data['_schema_type'] = schema.get('document_type')
            data['_page'] = page.get('_page')
            data['_filename'] = page.get('_filename')
            return data
        except Exception as e:
            page['_error'] = '%s: %s' % (type(e).__name__, str(e)[:220])
            return page

    text_pages = [p for p in tasks if p.get('_kind') == 'native' and
                  not p.get('_blank') and not p.get('_error')]
    vision_pages = [p for p in tasks if p.get('_kind') == 'scanned' and
                    not p.get('_blank') and not p.get('_error')]
    pools = []
    if text_pages:
        pools.append((ThreadPoolExecutor(max_workers=max(1, min(TEXT_WORKERS, len(text_pages)))),
                      text_pages))
    if vision_pages:
        pools.append((ThreadPoolExecutor(max_workers=max(1, min(VISION_WORKERS, len(vision_pages)))),
                      vision_pages))
    futures = []
    for pool, work in pools:
        futures.extend(pool.submit(run_page, p) for p in work)
    for p in tasks:
        if p.get('_blank') or p.get('_error'):
            results.append(p)
            done[0] += 1
            emit({'type': 'page', 'mode': 'blank' if p.get('_blank') else 'error',
                  'filename': p.get('_filename', ''), 'page': p.get('_page', 0),
                  'current': done[0], 'total_pages': total,
                  'error': p.get('_error')})
    for future in as_completed(futures):
        results.append(future.result())
        with lock:
            done[0] += 1
            current = done[0]
        page_mode = 'error' if results[-1].get('_error') else results[-1].get('_kind', 'native')
        emit({'type': 'page', 'mode': page_mode, 'filename': results[-1].get('_filename', ''),
              'page': results[-1].get('_page', 0), 'current': current,
              'total_pages': total, 'error': results[-1].get('_error')})
    for pool, _work in pools:
        pool.shutdown()
    emit({'type': 'progress', 'message': '按文档类型和边界分别归组…', 'pct': 96})
    records, issues = MM.assemble_pages(results, schemas, segment_issues)
    for pf in pfs:
        pf.close()
    _store_job(job_id, {'mode': 'mixed', 'records': records, 'schemas': schemas,
                        'issues': issues, 'validations': []})
    emit({'type': 'result', 'mode': 'mixed', 'job': job_id,
          'total_pages': total, 'records': len(records), 'issues': issues,
          'schemas': _mixed_schema_json(schemas),
          'rows': MM.rows(records, schemas)})


@app.route('/mixed/split', methods=['POST'])
def mixed_split():
    """异构文档专用流程：只快速分类、切分并保存，不做字段提取。"""
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': '没有上传文件'}), 400
    names = _uniq_names([safe_name(f.filename) for f in files])
    loaded = [(n, f.read()) for n, f in zip(names, files)]
    cfg = _cfg_from(request)

    def generate():
        q = queue.Queue()

        def worker():
            pfs = []
            try:
                q.put(_sse({'type': 'progress', 'mode': 'split',
                            'message': '扫描 PDF / 图片并准备快速分拣…', 'pct': 2}))
                _fast_split_loaded(loaded, cfg, lambda o: q.put(_sse(o)))
            except Exception as e:
                logger.error('异构文档快速分拣失败：%s', traceback.format_exc())
                q.put(_sse({'type': 'error', 'mode': 'split', 'message': str(e)[:400]}))
                for pf in pfs:
                    pf.close()
            finally:
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = q.get()
            if item is None:
                break
            yield item

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/mixed/run', methods=['POST'])
def mixed_run():
    """兼容旧前端入口；现在统一走“先分拣保存、后分别上传”流程。"""
    return mixed_split()


@app.route('/mixed/run-legacy', methods=['POST'])
def mixed_run_legacy():
    """一键：全页识别 → 文档拆分 → 按类型总结字段 → 分类型提取。"""
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': '没有上传文件'}), 400
    names = _uniq_names([safe_name(f.filename) for f in files])
    loaded = [(n, f.read()) for n, f in zip(names, files)]
    cfg = _cfg_from(request)
    job_id = uuid.uuid4().hex[:12]

    def generate():
        q = queue.Queue()

        def worker():
            pfs = []
            try:
                q.put(_sse({'type': 'progress', 'message': '扫描并识别混合文档页面…', 'pct': 2}))
                pfs, bad, pages, schemas, segment_issues, ai = _observe_mixed_loaded(
                    loaded, cfg, lambda o: q.put(_sse(o)))
                if not schemas:
                    raise ValueError('没有识别出可用的文档类型和字段方案')
                q.put(_sse({'type': 'schema', 'mode': 'mixed',
                            'schemas': _mixed_schema_json(schemas),
                            'document_types': [s.get('document_type') for s in schemas]}))
                _run_mixed_extraction(job_id, loaded, pfs, bad, pages, schemas,
                                      segment_issues, ai, cfg,
                                      lambda o: q.put(_sse(o)))
            except Exception as e:
                logger.error(traceback.format_exc())
                q.put(_sse({'type': 'error', 'message': str(e)[:400]}))
                for pf in pfs:
                    pf.close()
            finally:
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = q.get()
            if item is None:
                break
            yield item

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ══════════════════════════════════════════════════════════════
#  AI-2 字段描述补全
# ══════════════════════════════════════════════════════════════
@app.route('/api/complete_field', methods=['POST'])
def api_complete_field():
    d = request.json if request.is_json else request.form
    cfg = GatewayConfig(d.get('api_url') or DEFAULT_API_URL,
                        d.get('api_key') or DEFAULT_TOKEN,
                        d.get('model') or DEFAULT_MODEL)
    try:
        ai = _make_ai_call(cfg)
        raw, _ = ai('text', PS.COMPLETE_SYSTEM,
                    PS.complete_user(d.get('label', ''), d.get('type', 'text'),
                                     d.get('doc_context', '')), 16000)
        return jsonify({'description': (raw or '').strip().strip('"\'{}')[:60]})
    except Exception as e:
        logger.warning('补全失败: %s', e)
        return jsonify({'description': ''})


# ══════════════════════════════════════════════════════════════
#  提取（SSE）
# ══════════════════════════════════════════════════════════════
@app.route('/extract', methods=['POST'])
def extract():
    cfg = _cfg_from(request)
    try:
        fields = normalize_fields(json.loads(request.form.get('fields', '[]')))
    except Exception:
        return jsonify({'error': '字段定义不是合法 JSON'}), 400
    if not fields:
        return jsonify({'error': '未提供字段定义，请先分析或选择预设'}), 400
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': '没有上传文件'}), 400
    names = _uniq_names([safe_name(f.filename) for f in files])
    loaded = [(n, f.read()) for n, f in zip(names, files)]
    job_id = uuid.uuid4().hex[:12]

    def generate():
        q = queue.Queue()

        def worker():
            try:
                _run_job(job_id, loaded, fields, cfg, lambda o: q.put(_sse(o)))
            except Exception as e:
                logger.error(traceback.format_exc())
                q.put(_sse({'type': 'error', 'message': str(e)[:400]}))
            finally:
                q.put(None)

        th = threading.Thread(target=worker, daemon=True)
        th.start()
        while True:
            item = q.get()
            if item is None:
                break
            yield item

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/common/extract', methods=['POST'])
def common_extract():
    cfg = _cfg_from(request)
    try:
        fields = CM.normalize_common_fields(json.loads(request.form.get('fields', '[]')))
        document_types = json.loads(request.form.get('document_types', '[]'))
        if not isinstance(document_types, list):
            document_types = []
    except Exception:
        return jsonify({'error': '统一字段定义不是合法 JSON'}), 400
    if not fields:
        return jsonify({'error': '请先让 AI 总结公共字段'}), 400
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': '没有上传文件'}), 400
    names = _uniq_names([safe_name(f.filename) for f in files])
    loaded = [(n, f.read()) for n, f in zip(names, files)]
    job_id = uuid.uuid4().hex[:12]

    def generate():
        q = queue.Queue()

        def worker():
            try:
                _run_common_job(job_id, loaded, fields, document_types, cfg,
                                lambda o: q.put(_sse(o)))
            except Exception as e:
                logger.error(traceback.format_exc())
                q.put(_sse({'type': 'error', 'message': str(e)[:400]}))
            finally:
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = q.get()
            if item is None:
                break
            yield item

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/common/run', methods=['POST'])
def common_run():
    """一键完成：差异化采样 → AI 公共字段归纳 → 全量统一提取。"""
    cfg = _cfg_from(request)
    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({'error': '没有上传文件'}), 400
    names = _uniq_names([safe_name(f.filename) for f in files])
    loaded = [(n, f.read()) for n, f in zip(names, files)]
    job_id = uuid.uuid4().hex[:12]

    def generate():
        q = queue.Queue()

        def worker():
            pfs = []
            handed_off = False
            try:
                q.put(_sse({'type': 'progress', 'message': '扫描文件并比较页面差异…',
                            'pct': 2}))
                pfs, bad = _scan_common_loaded(loaded)
                if not pfs:
                    raise ValueError('没有可解析的 PDF 或图片')
                result, refs = _discover_common_from_pfs(
                    pfs, cfg, lambda o: q.put(_sse(o)))
                fields = result.get('fields') or []
                if not fields:
                    raise ValueError('AI 未归纳出可用的公共字段')
                q.put(_sse({'type': 'schema', 'mode': 'common',
                            'summary': result.get('summary', ''),
                            'document_types': result.get('document_types', []),
                            'fields': fields, 'sampled_pages': len(refs)}))
                handed_off = True
                _run_common_job(job_id, loaded, fields,
                                result.get('document_types', []), cfg,
                                lambda o: q.put(_sse(o)), pfs=pfs, bad=bad)
            except Exception as e:
                logger.error(traceback.format_exc())
                q.put(_sse({'type': 'error', 'message': str(e)[:400]}))
            finally:
                # 正常提取会在任务末尾关闭；异常时这里兜底。close 可重复调用。
                for pf in pfs:
                    pf.close()
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = q.get()
            if item is None:
                break
            yield item

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def _run_common_job(job_id, loaded, fields, document_types, cfg, emit,
                    pfs=None, bad=None):
    ai = _make_ai_call(cfg)
    caps = {'vision': True}
    if pfs is None:
        pfs, bad = _scan_common_loaded(loaded)
    bad = bad or []
    for name, error in bad:
        emit({'type': 'page', 'filename': name, 'page': 0, 'current': 0,
              'total_pages': 0, 'mode': 'error', 'error': '无法打开: %s' % error[:160]})
    if not pfs:
        emit({'type': 'error', 'message': '没有可解析的 PDF 或图片'})
        return

    tasks = [(pf, i) for pf in pfs for i in range(pf.page_count)]
    total = len(tasks)
    n_blank = sum(1 for pf, i in tasks if pf.pages[i].kind == 'blank')
    emit({'type': 'start', 'mode': 'common', 'total_pages': total, 'files': len(pfs),
          'blank_pages': n_blank, 'ocr': P.ocr_available(), 'job': job_id})
    results, done = [], [0]
    lock = threading.Lock()

    def finish(pf, idx, data, mode, error=None):
        data['_page'] = idx + 1
        data['_filename'] = pf.name
        with lock:
            results.append(data)
            done[0] += 1
            current = done[0]
        emit({'type': 'page', 'filename': pf.name, 'page': idx + 1,
              'current': current, 'total_pages': total, 'mode': mode, 'error': error})

    def run_page(pf, idx):
        page = pf.pages[idx]
        ctx = '[统一提取 %s p%d] ' % (pf.name, idx + 1)
        if page.kind == 'blank':
            finish(pf, idx, {'_blank': True, '_kind': 'blank'}, 'blank')
            return
        try:
            if page.kind == 'native':
                data = CM.common_extract_page(
                    fields, ai, kind='native', fname=pf.name, page_no=idx + 1,
                    total=pf.page_count, text=page.text, caps=caps,
                    document_types=document_types, ctx=ctx)
            else:
                img = pf.render(idx)
                b64 = P.pil_to_b64(img)
                hint = P.ocr_layout(img)
                data = CM.common_extract_page(
                    fields, ai, kind='scanned', fname=pf.name, page_no=idx + 1,
                    total=pf.page_count, text=page.hint, image_b64=b64,
                    ocr_hint=hint, caps=caps, document_types=document_types, ctx=ctx)
            finish(pf, idx, data, page.kind)
        except Exception as e:
            logger.warning('%s提取失败: %s', ctx, e)
            finish(pf, idx, {'_error': '%s: %s' % (type(e).__name__, str(e)[:220]),
                             '_evidence': 'failed', '_kind': page.kind}, 'error', str(e)[:220])

    text_tasks = [(pf, i) for pf, i in tasks if pf.pages[i].kind == 'native']
    other_tasks = [(pf, i) for pf, i in tasks if pf.pages[i].kind != 'native']
    tp = ThreadPoolExecutor(max_workers=max(1, min(TEXT_WORKERS, len(text_tasks) or 1)))
    vp = ThreadPoolExecutor(max_workers=max(1, min(VISION_WORKERS, len(other_tasks) or 1)))
    futures = [tp.submit(run_page, pf, i) for pf, i in text_tasks] + \
              [vp.submit(run_page, pf, i) for pf, i in other_tasks]
    for future in futures:
        future.result()
    tp.shutdown()
    vp.shutdown()

    emit({'type': 'progress', 'message': '结合全文顺序复核文档边界…', 'pct': 90})
    segment_issues = CM.refine_document_boundaries(ai, results, fields)
    emit({'type': 'progress', 'message': '按复核后的边界归组并统一字段…', 'pct': 96})
    records, issues = CM.assemble_common_pages(results, fields, segment_issues)
    for pf in pfs:
        pf.close()
    _store_job(job_id, {'mode': 'common', 'records': records, 'fields': fields,
                        'issues': issues, 'validations': []})
    emit({'type': 'result', 'mode': 'common', 'job': job_id,
          'total_pages': total, 'blank_pages': n_blank, 'records': len(records),
          'issues': issues,
          'fields': [{'key': f['key'], 'label': f['label'], 'type': f['type'],
                      'coverage': f.get('coverage', 0),
                      'source_variants': f.get('source_variants', []),
                      'columns': f.get('columns', [])} for f in fields],
          'rows': CM.common_rows(records, fields)})


def _run_job(job_id, loaded, fields, cfg, emit):
    ai = _make_ai_call(cfg)
    caps = {'vision': True}

    # 1) 结构扫描（本地，快；并发做）
    pfs, bad = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(lambda nb: P.open_file(nb[0], nb[1]).scan(), nb): nb[0]
                for nb in loaded}
        for fut, nm in futs.items():
            try:
                pfs.append(fut.result())
            except Exception as e:
                bad.append((nm, str(e)))
    pfs.sort(key=lambda pf: [n for n, _ in loaded].index(pf.name))
    for nm, err in bad:
        emit({'type': 'page', 'filename': nm, 'page': 0, 'current': 0,
              'total_pages': 0, 'mode': 'error', 'error': '无法打开: %s' % err[:160]})
    if not pfs:
        emit({'type': 'error', 'message': '没有可解析的 PDF 或图片'})
        return

    tasks = [(pf, i) for pf in pfs for i in range(pf.page_count)]
    total = len(tasks)
    n_blank = sum(1 for pf, i in tasks if pf.pages[i].kind == 'blank')
    emit({'type': 'start', 'total_pages': total, 'files': len(pfs),
          'blank_pages': n_blank, 'ocr': P.ocr_available(), 'job': job_id})

    # 2) 页级并发提取（全部文件摊平；文本/视觉分池）
    results, done = [], [0]
    lock = threading.Lock()

    def finish(pf, idx, data, mode, err=None):
        data['_page'] = idx + 1
        data['_filename'] = pf.name
        with lock:
            results.append(data)
            done[0] += 1
            cur = done[0]
        emit({'type': 'page', 'filename': pf.name, 'page': idx + 1, 'current': cur,
              'total_pages': total, 'mode': mode, 'error': err})

    def run_page(pf, idx):
        pi = pf.pages[idx]
        ctx = '[%s p%d] ' % (pf.name, idx + 1)
        if pi.kind == 'blank':
            finish(pf, idx, {'_blank': True, '_kind': 'blank'}, 'blank')
            return
        try:
            if pi.kind == 'native':
                data = extract_page(fields, ai, kind='native', fname=pf.name,
                                    page_no=idx + 1, total=pf.page_count,
                                    text=pi.text, caps=caps, ctx=ctx)
            else:
                img = pf.render(idx)
                b64 = P.pil_to_b64(img)
                hint = P.ocr_layout(img)
                data = extract_page(fields, ai, kind='scanned', fname=pf.name,
                                    page_no=idx + 1, total=pf.page_count,
                                    text=pi.hint, image_b64=b64, ocr_hint=hint,
                                    caps=caps, ctx=ctx)
            finish(pf, idx, data, pi.kind)
        except Exception as e:
            logger.warning('%s提取失败: %s', ctx, e)
            finish(pf, idx, {'_error': '%s: %s' % (type(e).__name__, str(e)[:220]),
                             '_evidence': 'failed', '_kind': pi.kind}, 'error',
                   err=str(e)[:220])

    text_tasks = [(pf, i) for pf, i in tasks if pf.pages[i].kind == 'native']
    other_tasks = [(pf, i) for pf, i in tasks if pf.pages[i].kind != 'native']
    tp = ThreadPoolExecutor(max_workers=max(1, min(TEXT_WORKERS, len(text_tasks) or 1)))
    vp = ThreadPoolExecutor(max_workers=max(1, min(VISION_WORKERS, len(other_tasks) or 1)))
    futs = [tp.submit(run_page, pf, i) for pf, i in text_tasks] + \
           [vp.submit(run_page, pf, i) for pf, i in other_tasks]
    for f in futs:
        f.result()
    tp.shutdown()
    vp.shutdown()

    # 3) 合并 + 校验
    emit({'type': 'progress', 'message': '合并与算术校验…', 'pct': 90})
    records, validations = merge_pages(results, fields)

    # 4) 不一致 → 自动复核一轮（更高清渲染 + 差额提示）
    issues = [v for v in validations if not v['match']]
    if issues and REPAIR_MAX > 0:
        by_rec = OrderedDict()
        for v in issues:
            by_rec.setdefault((v['file'], v['pages']), []).append(v)
        todo = list(by_rec.items())[:REPAIR_MAX]
        emit({'type': 'progress',
              'message': '发现 %d 处算术不一致，自动复核 %d 条记录…'
                         % (len(issues), len(todo)), 'pct': 92})
        pf_by_name = {pf.name: pf for pf in pfs}
        repaired = []
        for k, ((fname, pages), vs) in enumerate(todo):
            logger.info('[复核] 开始 %s p%s', fname, pages)
            note = repair_note_for(vs)
            pf = pf_by_name.get(fname)
            if pf is None:
                continue
            for pno in [int(x) for x in str(pages).split('+') if x.isdigit()]:
                idx = pno - 1
                if idx < 0 or idx >= pf.page_count:
                    continue
                pi = pf.pages[idx]
                ctx = '[复核 %s p%d] ' % (fname, pno)
                logger.info('%s开始复核', ctx)
                t0 = time.time()
                try:
                    b64 = None
                    if caps.get('vision', True):
                        logger.info('%s渲染大图...', ctx)
                        img = pf.render(idx, target_side=REPAIR_IMG_SIDE)
                        b64 = P.pil_to_b64(img, max_side=REPAIR_IMG_SIDE, quality=92)
                        logger.info('%s渲染完成(%.1fs)', ctx, time.time()-t0)
                        t0 = time.time()
                    hint = ''
                    if pi.kind != 'native':
                        hint = P.ocr_layout(pf.render(idx)) if not b64 else \
                               P.ocr_layout(img)
                        logger.info('%sOCR完成(%.1fs)', ctx, time.time()-t0)
                        t0 = time.time()
                    logger.info('%s发送AI请求...', ctx)
                    data = extract_page(
                        fields, ai, kind=pi.kind, fname=fname, page_no=pno,
                        total=pf.page_count, text=pi.text or pi.hint,
                        image_b64=b64, ocr_hint=hint, caps=caps,
                        repair_note=note, ctx=ctx)
                    logger.info('%sAI返回(%.1fs)', ctx, time.time()-t0)
                    data['_page'] = pno
                    data['_filename'] = fname
                    repaired.append(data)
                except Exception as e:
                    logger.warning('%s复核失败: %s', ctx, e)
            emit({'type': 'progress',
                  'message': '复核中… %d/%d' % (k + 1, len(todo)),
                  'pct': 92 + int(5 * (k + 1) / len(todo))})
        if repaired:
            results = splice_results(results, repaired)
            records, validations = merge_pages(results, fields)

    for pf in pfs:
        pf.close()

    # 5) 汇总输出
    passed = sum(1 for v in validations if v['match'])
    issues = [{'group': '%s p%s' % (v['file'], v['pages']), 'label': v['label'],
               'detail': '求和 %s ≠ 声明 %s（差 %s）'
                         % (v['sum_from_table'], v['declared'], v['diff']),
               'repaired': v.get('repaired', False)}
              for v in validations if not v['match']]
    _store_job(job_id, {'records': records, 'fields': fields,
                        'validations': validations})
    emit({'type': 'result', 'job': job_id, 'total_pages': total,
          'blank_pages': n_blank, 'records': len(records),
          'has_validation': bool(validations),
          'validation': {'total': len(validations), 'passed': passed,
                         'issues': issues},
          'fields': [{'key': f['key'], 'label': f['label'], 'type': f['type'],
                      'sum_check': bool(f.get('sum_check'))} for f in fields],
          'rows': _rows(records, fields)})


def _rows(records, fields):
    scalars = [f for f in fields if f['type'] != 'table']
    tables = [f for f in fields if f['type'] == 'table']
    rows = []
    for rec in records:
        row = {'_filename': rec.get('_filename', ''), '_pages': rec.get('_pages', ''),
               '_evidence': rec.get('_evidence', ''),
               '_confidence': rec.get('_confidence', ''),
               '_repaired': bool(rec.get('_repaired')),
               '_error': rec.get('_error')}
        for f in scalars:
            row[f['key']] = rec.get(f['key'])
            if f.get('sum_check'):
                row['_check_%s' % f['key']] = rec.get('_check_%s' % f['key'])
        row['_tables'] = {tf['key']: rec.get(tf['key'], []) for tf in tables}
        rows.append(row)
    return rows


# ══════════════════════════════════════════════════════════════
#  下载
# ══════════════════════════════════════════════════════════════
@app.route('/mixed/download')
def mixed_download():
    """下载某一类型 PDF；不指定 type 时下载包含全部分组的 ZIP。"""
    job_id = request.args.get('job', '')
    type_key = request.args.get('type', '')
    with _JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job or job.get('mode') != 'split':
        return jsonify({'error': '分类结果不存在或已过期，请重新分拣'}), 404
    groups = job.get('groups') or []
    if type_key:
        group = next((g for g in groups if str(g.get('key')) == str(type_key)), None)
        if not group:
            return jsonify({'error': '找不到该文档类型'}), 404
        path = group.get('file_path', '')
        if not path or not os.path.isfile(path):
            return jsonify({'error': '分组文件已被清理，请重新分拣'}), 404
        return send_file(path, mimetype='application/pdf', as_attachment=True,
                         download_name=group.get('file_name') or '分类文档.pdf')
    data = SM.zip_groups(groups, job.get('metadata') or {'job': job_id, 'groups': []})
    return send_file(io.BytesIO(data), mimetype='application/zip', as_attachment=True,
                     download_name='异构文档分类结果_%s.zip' % job_id)


@app.route('/download')
def download():
    job_id = request.args.get('job', '')
    with _JOBS_LOCK:
        job = JOBS.get(job_id) or (next(reversed(JOBS.values())) if JOBS else None)
    if not job:
        return jsonify({'error': '暂无数据，请先提取'}), 400
    if job.get('mode') == 'common':
        data = write_common_excel(job['records'], job['fields'], job.get('issues', []))
        filename = '统一字段提取结果.xlsx'
    elif job.get('mode') == 'mixed':
        data = write_mixed_excel(job['records'], job.get('schemas', []),
                                 job.get('issues', []))
        filename = '混合文档分类提取结果.xlsx'
    elif job.get('mode') == 'split':
        data = SM.zip_groups(job.get('groups', []),
                             job.get('metadata') or {'job': job_id, 'groups': []})
        filename = '异构文档分类结果_%s.zip' % job_id
        return send_file(io.BytesIO(data), mimetype='application/zip',
                         as_attachment=True, download_name=filename)
    else:
        data = write_excel(job['records'], job['fields'], job['validations'])
        filename = '提取结果.xlsx'
    return send_file(
        io.BytesIO(data),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name=filename)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('-p', '--port', type=int, default=5000)
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--debug', action='store_true')
    a = ap.parse_args()
    logger.info('=' * 56)
    logger.info(' 通用票据/文档提取服务 v7')
    logger.info('  网关 %s  模型 %s', DEFAULT_API_URL, DEFAULT_MODEL)
    logger.info('  文本并发 %d · 视觉并发 %d · 本地OCR %s',
                TEXT_WORKERS, VISION_WORKERS, '可用' if P.ocr_available() else '未安装')
    logger.info('  http://localhost:%d', a.port)
    logger.info('=' * 56)
    app.run(host=a.host, port=a.port, debug=a.debug, threaded=True)
