# -*- coding: utf-8 -*-
"""
app.py —— 通用票据/文档提取服务  v7
流程：上传(未知类型) → 三态判定 → AI 推荐字段(或预设) → 单页合并提取(并发)
      → 续页感知合并 → 本地算术校验 → 不一致自动复核一轮 → 结果/Excel

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
from concurrent.futures import ThreadPoolExecutor

from flask import (Flask, render_template, request, jsonify, Response,
                   send_file, make_response)

import pdf_utils as P
import presets as PS
from ai_client import GatewayConfig, AIClient, AIResponseError, robust_call, parse_json
from extractor import extract_page, repair_note_for
from merge import normalize_fields, merge_pages, splice_results
from excel_export import write_excel

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
    t0 = time.time()
    try:
        text, _ = ai('text', '你是回显器。', '只回复两个字：OK', 128000)
        out['text_ok'] = True
        out['text_ms'] = int((time.time() - t0) * 1000)
        out['echo'] = (text or '')[:40]
    except Exception as e:
        out['text_ok'] = False
        out['error'] = '%s: %s' % (type(e).__name__, str(e)[:300])
        return jsonify(out)
    t1 = time.time()
    try:
        ai('vision', '你是回显器。', '这是一张纯白测试图。只回复两个字：OK', 128000,
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
        pf = P.PdfFile(fname, fb).scan()
    except Exception as e:
        return jsonify({'error': '无法打开 PDF：%s' % e}), 400
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
        t, _ = robust_call(lambda: ai(kind, PS.ANALYZE_SYSTEM, u, 128000,
                                      image_b64=image_b64), ctx='[分析] ')
        return t
    raw = once(user)
    try:
        parse_json(raw)
        return raw
    except ValueError:
        return once(user + '\n\n（你上一次的输出无法解析为 JSON。请只输出 JSON 对象。）')


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
                                     d.get('doc_context', '')), 160)
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


def _run_job(job_id, loaded, fields, cfg, emit):
    ai = _make_ai_call(cfg)
    caps = {'vision': True}

    # 1) 结构扫描（本地，快；并发做）
    pfs, bad = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(lambda nb: P.PdfFile(nb[0], nb[1]).scan(), nb): nb[0]
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
        emit({'type': 'error', 'message': '没有可解析的 PDF'})
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
@app.route('/download')
def download():
    job_id = request.args.get('job', '')
    with _JOBS_LOCK:
        job = JOBS.get(job_id) or (next(reversed(JOBS.values())) if JOBS else None)
    if not job:
        return jsonify({'error': '暂无数据，请先提取'}), 400
    data = write_excel(job['records'], job['fields'], job['validations'])
    return send_file(
        io.BytesIO(data),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name='提取结果.xlsx')


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
