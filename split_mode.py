# -*- coding: utf-8 -*-
"""异构文件的快速分拣与保存。

这个模块只负责回答两个问题：每页属于什么文档类型、属于哪一份逻辑文档。
它不做字段建模和字段提取，避免把合同、发票、发货单强行压进一套字段。
"""
import io
import json
import os
import re
import zipfile
from collections import OrderedDict

import common_mode as CM


FAST_CLASSIFY_SYSTEM = """你是快速异构文档分拣器。只根据页面证据判断页面所属的文档类型和逻辑文档，
不要提取字段，不要总结字段，不要输出解释或 markdown。文档类型必须是简短、稳定的业务类别，
同一类文档即使版式不同也使用同一个类别名称；同一业务下标题或表格结构明显不同、后续字段方案也不同的子表，必须保留稳定的子类型名称。

输入是同一来源文件按顺序排列的页面摘要，可能存在合同、发票、发货单、银行对账单等类型交错。
输出严格为 JSON：
{"pages":[
  {"page":1,"document_type":"发票","document_no":"原始编号或null",
   "page_role":"first|continuation|single|unknown","anchor_page":1,
   "confidence":"high|medium|low","reason":"不超过40字的判断依据"}
]}

规则：
1. anchor_page 必须是本页或前面同一来源文件中该逻辑文档首页的页码；续页指向首页。
2. 有明确单号时优先用单号归组；没有单号时综合标题、主体、日期、续页措辞和内容连续性。
3. 不同文档类型不能合并；同一类型的不同版式可以归为同一类别，但不能因为类型相同就合并不同单据。
4. 有标题或表格证据时不要输出“未知文档”；只有证据确实不足时才可用“未知文档”。
5. 只返回输入页码，不得遗漏页面，不得增加页面。"""

FAST_CLASSIFY_TOKENS = int(os.environ.get('FAST_CLASSIFY_TOKENS', '1638400'))
FAST_BATCH_PAGES = int(os.environ.get('FAST_BATCH_PAGES', '6'))
FAST_TEXT_CHARS = int(os.environ.get('FAST_TEXT_CHARS', '2200'))


def _safe_type(value):
    value = str(value or '').strip()
    return value[:60] or '未知文档'


def _canonical(value):
    return CM._canonical(_safe_type(value)) or '未知文档'


def _page_payload(pf, idx, text=None):
    page = pf.pages[idx]
    return {
        'page': idx + 1,
        'kind': page.kind,
        'text': str(text if text is not None else (page.text or page.hint or ''))[:FAST_TEXT_CHARS],
    }


def _fallback_item(pf, idx):
    return {
        'page': idx + 1, 'document_type': '未知文档', 'document_no': None,
        'page_role': 'unknown', 'anchor_page': idx + 1,
        'confidence': 'low', 'reason': 'AI分拣失败，暂按单页保存',
    }


def _normalize_items(raw, pf, indices):
    returned = {}
    if isinstance(raw, dict):
        raw = raw.get('pages')
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                returned[int(item.get('page'))] = item
            except (TypeError, ValueError):
                continue
    out = []
    valid_pages = {i + 1 for i in indices}
    for idx in indices:
        pno = idx + 1
        item = dict(returned.get(pno) or _fallback_item(pf, idx))
        item['page'] = pno
        item['document_type'] = _safe_type(item.get('document_type'))
        item['document_no'] = CM._clean(item.get('document_no'))
        role = item.get('page_role')
        item['page_role'] = role if role in ('first', 'continuation', 'single', 'unknown') else 'unknown'
        try:
            anchor = int(item.get('anchor_page'))
        except (TypeError, ValueError):
            anchor = pno
        if anchor not in valid_pages or anchor > pno:
            anchor = pno
        item['anchor_page'] = anchor
        item['confidence'] = item.get('confidence') if item.get('confidence') in CM._CONF else 'low'
        item['reason'] = str(item.get('reason') or '')[:120]
        out.append(item)
    return out


def _returned_page_items(raw):
    raw = raw.get('pages') if isinstance(raw, dict) else raw
    if not isinstance(raw, list):
        return {}
    out = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            out[int(item.get('page'))] = item
        except (TypeError, ValueError):
            continue
    return out


def _is_network_failure(detail):
    text = str(detail or '').lower()
    return any(token in text for token in (
        'connecterror', 'connection', 'timeout', 'winerror',
        'server disconnected', 'transport', 'network'))


def classify_native_batches(ai_call, pf, indices, emit=None, ctx='[快速分拣] '):
    """电子 PDF 先按小批量请求；批量失败或漏页时自动降为单页重试。"""
    all_items = []
    for start in range(0, len(indices), max(1, FAST_BATCH_PAGES)):
        batch = indices[start:start + max(1, FAST_BATCH_PAGES)]
        user = json.dumps({'source_file': pf.name,
                           'pages': [_page_payload(pf, i) for i in batch]}, ensure_ascii=False)
        raw, batch_error = None, None
        try:
            raw = CM._ask_json(ai_call, 'text', FAST_CLASSIFY_SYSTEM, user,
                               FAST_CLASSIFY_TOKENS, None,
                               ctx + '%s p%d-%d ' % (pf.name, batch[0] + 1, batch[-1] + 1))
        except Exception as exc:
            batch_error = '%s: %s' % (type(exc).__name__, str(exc)[:120])
        returned = _returned_page_items(raw)
        recovered = {}
        for idx in batch:
            pno = idx + 1
            if pno in returned:
                recovered[pno] = _normalize_items(
                    {'pages': [returned[pno]]}, pf, [idx])[0]
                continue
            if batch_error and _is_network_failure(batch_error):
                item = _fallback_item(pf, idx)
                item['reason'] = 'AI网关连接失败，改按版式兜底：%s' % batch_error[:120]
                item['_classify_error'] = batch_error[:220]
                recovered[pno] = item
                continue
            # 批量请求可能因为上下文过长、网关截断或 JSON 不完整而漏页。
            # 只重试缺失页，正常批次仍保持低请求数。
            try:
                single_user = json.dumps({'source_file': pf.name,
                                          'pages': [_page_payload(pf, idx)]}, ensure_ascii=False)
                single_raw = CM._ask_json(
                    ai_call, 'text', FAST_CLASSIFY_SYSTEM, single_user,
                    FAST_CLASSIFY_TOKENS, None,
                    ctx + '%s p%d 单页重试 ' % (pf.name, pno))
                single_items = _returned_page_items(single_raw)
                if pno not in single_items:
                    raise ValueError('单页响应未返回当前页')
                recovered[pno] = _normalize_items(
                    {'pages': [single_items[pno]]}, pf, [idx])[0]
            except Exception as exc:
                item = _fallback_item(pf, idx)
                detail = batch_error or ('批量响应漏页；单页重试失败：%s' % str(exc)[:90])
                item['reason'] = 'AI分拣失败，待按版式兜底：%s' % detail[:120]
                item['_classify_error'] = detail[:220]
                recovered[pno] = item
        all_items.extend(recovered[pno] for pno in sorted(recovered))
        if emit:
            emit({'type': 'progress', 'message': '快速分拣《%s》%d/%d页…' %
                  (pf.name, min(start + len(batch), len(indices)), len(indices)),
                  'pct': 8 + int(32 * min(start + len(batch), len(indices)) /
                                 max(1, len(indices)))})
    return all_items


def classify_scanned_page(ai_call, pf, idx, image_b64, ocr_hint='', ctx='[快速分拣] '):
    """扫描页优先把 OCR 文字放进批量链路；没有 OCR 时才走一页一图的视觉请求。"""
    user = json.dumps({'source_file': pf.name,
                       'pages': [_page_payload(pf, idx, ocr_hint or pf.pages[idx].hint)]},
                      ensure_ascii=False)
    return CM._ask_json(ai_call, 'vision' if image_b64 else 'text',
                        FAST_CLASSIFY_SYSTEM, user, FAST_CLASSIFY_TOKENS,
                        image_b64, ctx + '%s p%d ' % (pf.name, idx + 1))


def _layout_signature(page):
    """生成与业务名称无关的粗版式指纹，作为 AI 失败时的最后兜底。"""
    meta = page.get('_layout_meta')
    if meta:
        width, height, lines, chars, images = meta
        orientation = 'portrait' if height >= width else 'landscape'
        return json.dumps((
            orientation,
            int(round(float(lines) / 40.0)),
            int(round(float(images))),
        ), ensure_ascii=False)
    text = str(page.get('_layout_text') or '').strip()
    if not text:
        return ''
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ''
    shape = (
        min(40, int(round(len(text) / 240.0))),
        min(80, int(round(len(lines) / 5.0))),
        min(80, int(round(sum(1 for line in lines if len(line) >= 45) / 3.0))),
        min(80, int(round(sum(1 for line in lines
                            if len(re.findall(r'\d', line)) >= 2) / 3.0))),
        min(80, int(round(sum(line.count('   ') for line in lines) / 10.0))),
    )
    return json.dumps(shape, ensure_ascii=False)


def apply_layout_fallback(pages):
    """AI 全部失败时按重复版式拆分，避免所有页静默落入一个“未知文档”。"""
    labels = OrderedDict()
    for page in sorted(pages, key=lambda p: (str(p.get('_filename', '')),
                                             int(p.get('_page', 0)))):
        if page.get('_blank'):
            continue
        dtype = _canonical(page.get('document_type'))
        if dtype not in ('', '未知文档', '未知'):
            continue
        pf = page.get('_source_pf')
        idx = page.get('_source_idx')
        if pf is not None and idx is not None:
            info = pf.pages[int(idx)]
            page['_layout_text'] = info.text or info.hint or ''
            if pf.__class__.__name__ == 'PdfFile':
                try:
                    cache = getattr(pf, '_split_layout_meta', None)
                    if cache is None:
                        import pdfplumber
                        with pdfplumber.open(io.BytesIO(pf.data)) as pdf:
                            cache = [(float(item.width), float(item.height),
                                      len(item.lines), len(item.chars), len(item.images))
                                     for item in pdf.pages]
                        pf._split_layout_meta = cache
                    if int(idx) < len(cache):
                        page['_layout_meta'] = cache[int(idx)]
                except Exception:
                    pass
        signature = _layout_signature(page)
        if not signature:
            continue
        if signature not in labels:
            labels[signature] = '未知文档·版式%02d' % (len(labels) + 1)
        label = labels[signature]
        page['document_type'] = label
        page['reason'] = (str(page.get('reason') or '') + '；按重复版式兜底分组')[:120]
        page['confidence'] = 'low'
        page['_layout_fallback'] = True
    return pages


def apply_local_boundaries(pages):
    """校正模型返回的锚点，确保不会把不同类型或不同编号串成一份。"""
    ordered = sorted(pages, key=lambda p: (str(p.get('_filename', '')), int(p.get('_page', 0))))
    by_file = OrderedDict()
    for p in ordered:
        by_file.setdefault(str(p.get('_filename', '')), []).append(p)
    for _fname, items in by_file.items():
        known = {}
        last_by_type = {}
        for p in items:
            pno = int(p.get('_page', 0))
            dtype = _safe_type(p.get('document_type'))
            key = _canonical(dtype)
            doc_no = CM._clean(p.get('document_no'))
            candidate = p.get('anchor_page')
            try:
                candidate = int(candidate)
            except (TypeError, ValueError):
                candidate = pno
            anchor_page = known.get(candidate)
            if anchor_page is None or anchor_page > pno:
                anchor_page = pno
            # 同一原始编号优先；没有编号时只对明确续页沿用同类型最近首页。
            if doc_no:
                for prior in reversed(items):
                    if int(prior.get('_page', 0)) >= pno:
                        continue
                    if (_canonical(prior.get('document_type')) == key and
                            CM._canonical(prior.get('document_no')) == CM._canonical(doc_no)):
                        anchor_page = int(prior.get('_segment_anchor') or prior.get('_page'))
                        break
            elif p.get('page_role') == 'continuation' and key in last_by_type:
                anchor_page = last_by_type[key]
            if anchor_page > pno:
                anchor_page = pno
            p['_segment_anchor'] = anchor_page
            p['_document_type'] = dtype
            p['_document_no'] = doc_no
            p['_page_role'] = p.get('page_role') or 'unknown'
            p['_confidence'] = p.get('confidence') if p.get('confidence') in CM._CONF else 'low'
            p['_segment_reason'] = p.get('reason', '')
            known[pno] = anchor_page
            if p['_page_role'] != 'continuation' or key not in last_by_type:
                last_by_type[key] = anchor_page
    return ordered


def type_groups(pages):
    """按类型聚合待保存页面，保留每份逻辑文档的页段元数据。"""
    groups = OrderedDict()
    docs = OrderedDict()
    for page in apply_local_boundaries(pages):
        if page.get('_blank'):
            continue
        dtype = _safe_type(page.get('_document_type'))
        type_key = _canonical(dtype)
        anchor = int(page.get('_segment_anchor') or page.get('_page'))
        doc_key = (page.get('_filename'), anchor)
        docs.setdefault((type_key, doc_key), []).append(page)
        groups.setdefault(type_key, {'key': type_key, 'document_type': dtype,
                                     'pages': [], 'documents': OrderedDict()})
        groups[type_key]['pages'].append(page)
        groups[type_key]['documents'].setdefault(doc_key, []).append(page)
    out = []
    for group in groups.values():
        out.append(group)
    return out


def _slug(value):
    text = re.sub(r'[^0-9A-Za-z\u4e00-\u9fff._-]+', '_', str(value or '未知文档')).strip(' ._')
    return (text or '未知文档')[:80]


def _image_page_pdf(pf, idx):
    from PIL import Image
    img = None
    try:
        if hasattr(pf, 'data'):
            with Image.open(io.BytesIO(pf.data)) as src:
                src.seek(idx)
                img = src.convert('RGB')
        if img is None:
            img = pf.render(idx)
        buf = io.BytesIO()
        img.save(buf, format='PDF', resolution=150.0)
        return buf.getvalue()
    finally:
        if img is not None:
            img.close()


def save_type_files(groups, pfs, job_id, root_dir):
    """用 pypdfium2 原页导入生成按类型 PDF；图片页转为 PDF 页，不损失分组顺序。"""
    import pypdfium2 as pdfium
    os.makedirs(root_dir, exist_ok=True)
    pf_by_name = {pf.name: pf for pf in pfs}
    saved = []
    for group in groups:
        type_dir = os.path.join(root_dir, _slug(group['document_type']))
        os.makedirs(type_dir, exist_ok=True)
        out_name = '%s_%s.pdf' % (_slug(group['document_type']), _slug(job_id))
        out_path = os.path.join(type_dir, out_name)
        dest = pdfium.PdfDocument.new()
        sources = {}
        try:
            for page in sorted(group['pages'], key=lambda p: (str(p.get('_filename', '')),
                                                               int(p.get('_page', 0)))):
                pf = pf_by_name.get(page.get('_filename'))
                if pf is None:
                    continue
                idx = int(page.get('_source_idx', page.get('_page', 1) - 1))
                if pf.__class__.__name__ == 'PdfFile':
                    if pf.name not in sources:
                        sources[pf.name] = pdfium.PdfDocument(io.BytesIO(pf.data))
                    src = sources[pf.name]
                    dest.import_pages(src, pages=[idx])
                else:
                    img_pdf = pdfium.PdfDocument(io.BytesIO(_image_page_pdf(pf, idx)))
                    dest.import_pages(img_pdf, pages=[0])
                    img_pdf.close()
            dest.save(out_path)
        finally:
            dest.close()
            for src in sources.values():
                src.close()
        group['file_name'] = out_name
        group['file_path'] = out_path
        group['page_count'] = len(group['pages'])
        group['logical_documents'] = len(group['documents'])
        group['fallback_pages'] = sum(1 for p in group['pages'] if p.get('_layout_fallback'))
        group['source_files'] = sorted({p.get('_filename', '') for p in group['pages']})
        group['document_segments'] = [{
            'source_file': key[0], 'anchor_page': key[1],
            'pages': [int(p.get('_page', 0)) for p in pages],
            'document_no': next((p.get('_document_no') for p in pages
                                 if p.get('_document_no')), None),
        } for key, pages in group['documents'].items()]
        saved.append(group)
    metadata_groups = []
    for group in saved:
        item = {k: v for k, v in group.items() if k not in ('pages', 'documents', 'file_path')}
        item['download_name'] = group.get('file_name', '')
        metadata_groups.append(item)
    metadata = {'job': job_id, 'groups': metadata_groups}
    with open(os.path.join(root_dir, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(metadata, fh, ensure_ascii=False, indent=2)
    return saved, metadata


def zip_groups(groups, metadata):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for group in groups:
            path = group.get('file_path')
            if path and os.path.isfile(path):
                zf.write(path, arcname=os.path.join(_slug(group.get('document_type')), group['file_name']))
        zf.writestr('manifest.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    return buf.getvalue()
