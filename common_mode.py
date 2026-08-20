# -*- coding: utf-8 -*-
"""异构票据统一字段模式。

该模块不包含任何票据类型、标题或字段名规则。文档类型、公共字段、字段映射和
页面边界均由模型根据当前批次的文档证据判断；本地代码只负责采样、规范化和归组。
"""
import json
import os
import re
from collections import OrderedDict

from ai_client import AIResponseError
from extractor import _ask_json, coerce


_SCALAR_TYPES = {'text', 'number', 'date', 'checkbox', 'multiline'}
_FIELD_TYPES = _SCALAR_TYPES | {'table'}
_CONF = {'low': 0, 'medium': 1, 'high': 2}
# 公共字段发现是短 JSON 任务。额度过大反而会让思考模型长时间推理、不输出正文。
# 正式同类票据模式的 token 设置不受这里影响。
COMMON_OBSERVE_TOKENS = int(os.environ.get('COMMON_OBSERVE_TOKENS', '8192'))
COMMON_BATCH_TOKENS = int(os.environ.get('COMMON_BATCH_TOKENS', '16384'))
COMMON_ANALYZE_TOKENS = int(os.environ.get('COMMON_ANALYZE_TOKENS', '32768'))
COMMON_EXTRACT_TOKENS = int(os.environ.get('COMMON_EXTRACT_TOKENS', '65536'))
COMMON_SEGMENT_TOKENS = int(os.environ.get('COMMON_SEGMENT_TOKENS', '32768'))
COMMON_SEGMENT_PAGES = int(os.environ.get('COMMON_SEGMENT_PAGES', '40'))
COMMON_SEGMENT_ACTIVE = int(os.environ.get('COMMON_SEGMENT_ACTIVE', '80'))
COMMON_SAMPLE_PAGES = int(os.environ.get('COMMON_SAMPLE_PAGES', '64'))


INVENTORY_SYSTEM = """你是通用文档字段观察器。分析当前单页，不预设文档种类。
只输出一个 JSON 对象，不要 markdown 或解释：
{
  "document_type": "根据本页内容得到的简短文档类别；无法判断则为未知",
  "page_role": "first|continuation|single|unknown",
  "fields": [
    {"source_label":"页面原字段名或栏目名", "semantic":"该字段在当前文档中的业务含义",
     "type":"text|number|date|checkbox|multiline|table", "example":"页面上的简短示例值或null",
     "columns":[{"source_label":"明细原列名", "semantic":"该列业务含义", "type":"text|number|date"}]}
  ]
}
规则：
1. 发现对跨格式汇总有意义的标量字段；存在重复行明细时，将整组明细作为 table 并列出有业务意义的列。
2. semantic 描述业务含义，不能只是重复 source_label。
3. 只根据证据，不补造页面没有的字段。
4. 名称、语言和位置不是判断字段含义的唯一依据，要结合上下文和文档用途。"""


CONSOLIDATE_SYSTEM = """你是跨格式文档字段建模器。输入是同一批上传文件中若干代表页的
字段观察结果。请按业务语义归并名称、语言和位置不同但含义相同的字段，生成一套能应用于
本批全部文档的统一字段方案。不得按固定票据种类套模板。

只输出一个 JSON 对象：
{
  "summary": "本批文档的简短概况",
  "document_types": ["观察到的文档类别"],
  "fields": [
    {"key":"英文snake_case", "label":"统一中文字段名",
     "type":"text|number|date|checkbox|multiline|table",
     "description":"完整业务定义及不同文档中的取值规则；无法确认时返回null",
     "source_variants":["观察到的原字段名"],
     "columns":[{"key":"英文snake_case", "label":"统一列名", "type":"text|number|date",
                  "description":"该列跨版式业务定义", "source_variants":["观察到的原列名"]}],
     "coverage":0.0,
     "merge_confidence":"high|medium|low"}
  ]
}

规则：
1. 推荐 4-12 个适合横向汇总的字段，优先选择跨文档类别重复出现的字段。
   银行流水、商品项目、发货明细等重复行应建模为 table；不同版式中业务含义相同的列要统一。
2. coverage 是代表页中适用该语义字段的比例，范围 0-1；不要为了提高覆盖率强行合并。
3. 业务含义不同的字段必须分开，例如含税总额与不含税金额、签订日期与到期日期。
4. 名称相似但角色不同不能合并；名称不同但业务角色等价可以合并。
5. description 必须足够明确，使另一个模型仅凭语义定义即可在不同版式中定位字段。
6. 所有 key 唯一，只输出 JSON。"""


SEGMENT_SYSTEM = """你是通用文档分页与边界复核器。输入包含同一个来源文件按顺序排列的
页面初步识别结果，以及前面仍可能继续的逻辑文档锚点。你必须综合文档类别、原始编号、标题、
日期、主体、金额、页码措辞、首页/续页信号和相邻关系，判断每页属于哪一份逻辑文档。
不预设票据种类，也不能仅凭页面相邻或字段名相似就合并；不同类别可以交错出现。

只输出一个 JSON 对象：
{"pages":[
  {"page":1, "anchor_page":1, "document_type":"规范化类别", "document_no":"原编号或null",
   "confidence":"high|medium|low", "reason":"简短边界证据"}
]}

规则：
1. anchor_page 是该逻辑文档在当前文件中最早已知页面。新文档必须指向自身；续页指向输入中
   已存在的有效锚点。不得输出输入没有提供的页码，不得指向未来页。
2. 同一编号且类别语义相同通常属于同一文档；编号不同必须分开。编号缺失时综合其他身份线索。
3. first/single 强烈提示新边界，但若单页初判与全局证据冲突，应以全局证据修正。
4. 合同附件、票据附页、交易明细续页应归入其主文档；无法可靠判断时不要强行合并，
   新建锚点并给 low confidence。
5. 当前批次的每个 page 必须且只能返回一次。只输出 JSON。"""


def normalize_common_fields(raw):
    """规范统一字段，同时保留模型给出的语义归并依据。"""
    out, seen = [], set()
    for i, f in enumerate(raw or []):
        if not isinstance(f, dict):
            continue
        key = re.sub(r'[^A-Za-z0-9_]+', '_', str(f.get('key') or '')).strip('_')
        key = key or 'field_%d' % (i + 1)
        if key in seen:
            key = '%s_%d' % (key, i + 1)
        seen.add(key)
        ftype = f.get('type') if f.get('type') in _FIELD_TYPES else 'text'
        variants = f.get('source_variants')
        if not isinstance(variants, list):
            variants = []
        try:
            coverage = max(0.0, min(1.0, float(f.get('coverage', 0))))
        except (TypeError, ValueError):
            coverage = 0.0
        columns = _normalize_columns(f.get('columns') or []) if ftype == 'table' else []
        # 兼容人工在说明里写“列：key 中文名, ...”的旧编辑方式。
        if ftype == 'table' and not columns:
            columns = _columns_from_description(f.get('description') or '')
        out.append({
            'key': key,
            'label': str(f.get('label') or key).strip() or key,
            'type': ftype,
            'description': str(f.get('description') or '').strip(),
            'source_variants': [str(x).strip() for x in variants if str(x).strip()][:20],
            'coverage': coverage,
            'merge_confidence': f.get('merge_confidence')
                                if f.get('merge_confidence') in _CONF else '',
            # 与现有字段编辑器兼容，但新模式不使用这些同类票据设置。
            'group_key': False, 'carry': 'first', 'sum_check': None, 'columns': columns,
        })
    return out


def _normalize_columns(raw):
    out, seen = [], set()
    for i, col in enumerate(raw or []):
        if not isinstance(col, dict):
            continue
        key = re.sub(r'[^A-Za-z0-9_]+', '_', str(col.get('key') or '')).strip('_')
        key = key or 'column_%d' % (i + 1)
        if key in seen:
            key = '%s_%d' % (key, i + 1)
        seen.add(key)
        ctype = col.get('type') if col.get('type') in _SCALAR_TYPES else 'text'
        variants = col.get('source_variants')
        if not isinstance(variants, list):
            variants = []
        out.append({
            'key': key,
            'label': str(col.get('label') or key).strip() or key,
            'type': ctype,
            'description': str(col.get('description') or '').strip(),
            'source_variants': [str(x).strip() for x in variants if str(x).strip()][:20],
        })
    return out


def _columns_from_description(description):
    match = re.search(r'(?:列|columns?)\s*[：:]\s*(.+)', str(description), re.I)
    if not match:
        return []
    raw = []
    for i, part in enumerate(re.split(r'[,，;；]\s*', match.group(1))):
        bits = part.strip().split(None, 1)
        if not bits:
            continue
        raw.append({'key': bits[0], 'label': bits[1] if len(bits) > 1 else bits[0],
                    'type': 'text'})
    return _normalize_columns(raw)


def representative_pages(pdfs, max_pages=None):
    """用内容差异度挑代表页，不依赖票据标题、银行名称或固定字段。

    先保证每个文件至少有一个样本，再用字符片段 Jaccard 距离做最远点采样。
    扫描页缺少文本时以文件内均匀位置补样，避免纯图片版式被漏掉。
    """
    max_pages = max(1, int(max_pages or COMMON_SAMPLE_PAGES))
    candidates = []
    by_file = []
    for pf in pdfs:
        valid = [(pf, i) for i, p in enumerate(pf.pages) if p.kind != 'blank']
        if not valid:
            continue
        by_file.append(valid)
        for item in valid:
            page = item[0].pages[item[1]]
            candidates.append((item[0], item[1], _page_fingerprint(page)))
    # 至少观察每个来源文件的一页，避免小文件或罕见版式被大文件挤掉。
    max_pages = max(max_pages, len(by_file))
    if len(candidates) <= max_pages:
        return [(pf, i) for pf, i, _ in candidates]

    selected, selected_keys = [], set()
    # 多文件时轮询选取各文件的首个有效页，避免大文件挤掉小文件。
    for valid in by_file:
        if len(selected) >= max_pages:
            break
        pf, i = valid[0]
        key = (id(pf), i)
        selected.append(next(x for x in candidates if x[0] is pf and x[1] == i))
        selected_keys.add(key)

    # 各文件的末页是通用边界样本；同样不假定任何文档类型。
    for valid in by_file:
        if len(selected) >= max_pages:
            break
        pf, i = valid[-1]
        key = (id(pf), i)
        if key not in selected_keys:
            selected.append(next(x for x in candidates if x[0] is pf and x[1] == i))
            selected_keys.add(key)

    while len(selected) < max_pages:
        best, best_score = None, -1.0
        for cand in candidates:
            key = (id(cand[0]), cand[1])
            if key in selected_keys:
                continue
            score = min(_fingerprint_distance(cand[2], s[2]) for s in selected)
            # 纯图页指纹相同时，用页码距离打破平局，形成均匀采样。
            page_spread = min(abs(cand[1] - s[1]) /
                              max(1, cand[0].page_count) for s in selected
                              if s[0] is cand[0]) if any(s[0] is cand[0] for s in selected) else 1
            score += page_spread * 0.05
            if score > best_score:
                best, best_score = cand, score
        if best is None:
            break
        selected.append(best)
        selected_keys.add((id(best[0]), best[1]))
    return [(pf, i) for pf, i, _ in selected]


def _page_fingerprint(page):
    text = (page.text or page.hint or '').lower()
    text = re.sub(r'\d+', '0', text)
    text = re.sub(r'\s+', ' ', text)[:12000]
    if not text:
        return {'kind:' + page.kind}
    compact = re.sub(r'\s+', '', text)
    grams = {compact[i:i + 4] for i in range(0, max(1, len(compact) - 3), 3)}
    # 控制长文档内存，同时保留确定性的分布样本。
    if len(grams) > 1200:
        grams = set(sorted(grams)[:1200])
    grams.add('kind:' + page.kind)
    return grams


def _fingerprint_distance(a, b):
    union = len(a | b)
    return 1.0 - (len(a & b) / union if union else 1.0)


def inventory_user(kind, fname, page_no, total, text='', ocr_hint='', with_image=False):
    source = 'PDF版式文本' if kind == 'native' else ('扫描图片' if with_image else 'OCR文本')
    parts = ['【代表页 · 文件《%s》第 %d/%d 页 · %s】' %
             (fname, page_no, total, source)]
    evidence = text if kind == 'native' else (ocr_hint or text)
    if evidence:
        parts.append(evidence[:8000])
    parts.append('请观察本页并输出 JSON。')
    return '\n\n'.join(parts)


def observe_page(ai_call, *, kind, fname, page_no, total, text='', image_b64=None,
                 ocr_hint='', caps=None, ctx=''):
    """让模型独立观察一个代表页，供后续跨文档语义归并。"""
    caps = caps if caps is not None else {}
    use_vision = bool(image_b64) and caps.get('vision', True)

    def run(with_image):
        user = inventory_user(kind, fname, page_no, total, text, ocr_hint, with_image)
        return _ask_json(ai_call, 'vision' if with_image else 'text', INVENTORY_SYSTEM,
                         user, COMMON_OBSERVE_TOKENS,
                         image_b64 if with_image else None, ctx)

    try:
        return run(use_vision)
    except AIResponseError as e:
        if not (e.no_vision and use_vision):
            raise
        caps['vision'] = False
        if not (ocr_hint or text):
            raise
        return run(False)


def discover_from_inventories(ai_call, inventories, ctx='[公共字段归纳] ', batch_size=4):
    """分批归纳再合并，避免把大量不同版式一次塞给思考模型。"""
    if not inventories:
        return {'summary': '', 'document_types': [], 'fields': []}
    partials = []
    for start in range(0, len(inventories), max(1, batch_size)):
        batch = inventories[start:start + max(1, batch_size)]
        user = ('以下是 %d 个代表页的独立观察结果。请归并为候选统一字段方案：\n\n' %
                len(batch)) + json.dumps(batch, ensure_ascii=False)
        data = _ask_json(ai_call, 'text', CONSOLIDATE_SYSTEM, user,
                         COMMON_BATCH_TOKENS, None,
                         ctx + '[批次%d] ' % (start // max(1, batch_size) + 1))
        partials.append({
            'summary': data.get('summary', ''),
            'document_types': data.get('document_types') or [],
            'fields': data.get('fields') or [],
        })
    if len(partials) == 1:
        data = partials[0]
    else:
        user = ('以下是各批代表页得到的候选方案。请再次按业务语义去重合并，'
                '保留跨批次重复出现的公共含义，不要因名称相似而误合并：\n\n' +
                json.dumps(partials, ensure_ascii=False))
        data = _ask_json(ai_call, 'text', CONSOLIDATE_SYSTEM, user,
                         COMMON_ANALYZE_TOKENS, None, ctx + '[最终合并] ')
    return {
        'summary': str(data.get('summary') or '').strip(),
        'document_types': [str(x).strip() for x in (data.get('document_types') or [])
                           if str(x).strip()],
        'fields': normalize_common_fields(data.get('fields') or []),
    }


def build_extract_system(fields, document_types=None):
    lines = [
        '你是异构文档统一字段提取器。当前页面可能来自任意类型、任意语言和任意版式的文档。',
        '不要依赖固定字段名或固定坐标，要根据字段的业务定义、上下文、文档角色和数值关系寻找语义等价值。',
        '只输出一个 JSON 对象，不要 markdown 或解释。', '',
    ]
    if document_types:
        lines.append('本批此前观察到的类别：%s。语义相同的类别必须使用列表中的原名称，'
                     '尤其续页不得另造“某某续页”类别；确实不属于这些类别时才给出新类别。' %
                     '、'.join(document_types[:20]))
    lines += ['统一字段：']
    for f in fields:
        variants = ('；观察到的原名：' + '、'.join(f.get('source_variants') or [])) \
                   if f.get('source_variants') else ''
        columns_note = ''
        if f['type'] == 'table':
            columns_note = '；统一列：' + '、'.join(
                '%s(%s，%s)' % (c['key'], c['type'], c.get('description') or c['label'])
                for c in (f.get('columns') or []))
        lines.append('- %s (%s) %s：%s%s' %
                     (f['key'], f['type'], f['label'], f['description'],
                      variants + columns_note))
    lines += [
        '', '输出格式：', '{',
        '  "_document_type": "本页所属文档的简短类别",',
        '  "_document_no": "本逻辑文档最稳定的原始编号；本页没有则为null",',
        '  "_page_role": "first|continuation|single|unknown",',
        '  "_page_summary": "不超过60字的本页角色和内容摘要",',
        '  "_identity_hints": [{"label":"身份线索原名", "value":"原值", "role":"该线索如何标识文档"}],',
        '  "_confidence": "high|medium|low",',
    ]
    for f in fields:
        if f['type'] == 'table':
            lines.append('  "%s": {"rows": [{%s}], "source_label": "原表名或null", '
                         '"evidence": "表头/行范围短证据或null", '
                         '"confidence": "high|medium|low", '
                         '"status": "found|not_found|not_applicable|ambiguous"},' %
                         (f['key'], ', '.join('"%s": ...' % c['key']
                                              for c in (f.get('columns') or []))))
        else:
            lines.append('  "%s": {"value": ..., "source_label": "原栏目名或null", '
                         '"evidence": "支持该值的短原文或null", '
                         '"confidence": "high|medium|low", '
                         '"status": "found|not_found|not_applicable|ambiguous"},' % f['key'])
    lines += [
        '}', '', '规则：',
        '1. 字段名和位置可以不同，只要业务含义等价即可映射；但不能把含义相近但用途不同的字段强行合并。',
        '2. 所有值必须来自当前页面证据。找不到填 null；存在多个无法取舍的候选时 status=ambiguous。',
        '3. number 只保留数字、小数点和负号；date 转为 YYYY-MM-DD。',
        '4. _document_no 是当前逻辑文档自己的编号，不是任意关联编号。',
        '5. continuation 表示本页只是同一逻辑文档的续页，即使文件中间穿插过其他类别页面也不改变此判断。',
        '6. source_label 与 evidence 用于人工追溯，必须简短且忠于原文。',
        '7. table 必须逐行输出当前页真实存在的明细，使用统一列 key；不得把表头、合计行或上一页重复表头当明细。',
        '8. _identity_hints 只放能帮助跨页归组的真实线索，例如单号、账号、合同号、主体、期间；最多8项。',
    ]
    return '\n'.join(lines)


def common_extract_page(fields, ai_call, *, kind, fname, page_no, total,
                        text='', image_b64=None, ocr_hint='', caps=None,
                        document_types=None, ctx=''):
    caps = caps if caps is not None else {}
    use_vision = bool(image_b64) and caps.get('vision', True)
    system = build_extract_system(fields, document_types)

    def run(with_image):
        user = inventory_user(kind, fname, page_no, total, text, ocr_hint, with_image)
        return _ask_json(ai_call, 'vision' if with_image else 'text', system, user,
                         COMMON_EXTRACT_TOKENS,
                         image_b64 if with_image else None, ctx)

    try:
        data = run(use_vision)
    except AIResponseError as e:
        if not (e.no_vision and use_vision):
            raise
        caps['vision'] = False
        if not (ocr_hint or text):
            raise
        data = run(False)
        data['__forced_text'] = True

    out = {
        '_document_type': str(data.get('_document_type') or '未知').strip() or '未知',
        '_document_no': _clean(data.get('_document_no')),
        '_page_role': data.get('_page_role') if data.get('_page_role') in
                      ('first', 'continuation', 'single', 'unknown') else 'unknown',
        '_page_summary': str(data.get('_page_summary') or '').strip()[:240],
        '_identity_hints': _normalize_identity_hints(data.get('_identity_hints')),
        '_confidence': data.get('_confidence') if data.get('_confidence') in _CONF else '',
        '_field_meta': {}, '_kind': kind,
    }
    out['_is_continuation'] = out['_page_role'] == 'continuation'
    out['_evidence'] = ('ocr_text' if data.get('__forced_text') else
                        ('native_text' if kind == 'native' else
                         ('vision' if use_vision and caps.get('vision', True) else 'ocr_text')))
    for f in fields:
        item = data.get(f['key'])
        if f['type'] == 'table':
            rows = item.get('rows') if isinstance(item, dict) else item
            out[f['key']] = _normalize_table_rows(rows, f.get('columns') or [])
            value_found = bool(out[f['key']])
            out['_field_meta'][f['key']] = _field_meta(
                item if isinstance(item, dict) else {}, value_found)
            continue
        if isinstance(item, dict):
            value = item.get('value')
            status = item.get('status')
            meta = {
                'source_label': _clean(item.get('source_label')),
                'evidence': _clean(item.get('evidence')),
                'confidence': item.get('confidence') if item.get('confidence') in _CONF else '',
                'status': status if status in
                          ('found', 'not_found', 'not_applicable', 'ambiguous') else
                          ('found' if value not in (None, '') else 'not_found'),
            }
        else:
            value = item
            meta = {'source_label': None, 'evidence': None, 'confidence': '',
                    'status': 'found' if value not in (None, '') else 'not_found'}
        out[f['key']] = coerce(value, f['type'])
        out['_field_meta'][f['key']] = meta
    return out


def _field_meta(item, value_found):
    status = item.get('status')
    return {
        'source_label': _clean(item.get('source_label')),
        'evidence': _clean(item.get('evidence')),
        'confidence': item.get('confidence') if item.get('confidence') in _CONF else '',
        'status': status if status in ('found', 'not_found', 'not_applicable', 'ambiguous')
                  else ('found' if value_found else 'not_found'),
    }


def _normalize_identity_hints(raw):
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not _clean(item.get('value')):
            continue
        out.append({'label': str(item.get('label') or '').strip()[:80],
                    'value': str(item.get('value')).strip()[:160],
                    'role': str(item.get('role') or '').strip()[:120]})
    return out[:8]


def _normalize_table_rows(raw, columns):
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if columns:
            row = {c['key']: coerce(item.get(c['key']), c['type']) for c in columns}
        else:
            row = {str(k): v for k, v in item.items() if not str(k).startswith('_')}
        if any(v not in (None, '') for v in row.values()):
            out.append(row)
    return out


def refine_document_boundaries(ai_call, page_results, fields, ctx='[文档边界复核] '):
    """用全局页序与活跃文档锚点复判边界，并把锚点写回各页。

    失败时逐文件退回确定性归组，不让边界模型故障拖垮已经完成的字段提取。
    返回可直接并入结果异常列表的说明。
    """
    issues = []
    by_file = OrderedDict()
    for p in sorted(page_results, key=lambda x: (str(x.get('_filename', '')),
                                                  int(x.get('_page', 0)))):
        if not p.get('_blank') and not p.get('_error'):
            by_file.setdefault(str(p.get('_filename', '')), []).append(p)
    for fname, pages in by_file.items():
        assignments, active = {}, OrderedDict()
        chunk_size = max(5, COMMON_SEGMENT_PAGES)
        for start in range(0, len(pages), chunk_size):
            chunk = pages[start:start + chunk_size]
            known = list(active.values())[-max(1, COMMON_SEGMENT_ACTIVE):]
            payload = {
                'source_file': fname,
                'active_documents': known,
                'pages': [_segment_manifest(p, fields) for p in chunk],
            }
            try:
                data = _ask_json(ai_call, 'text', SEGMENT_SYSTEM,
                                 json.dumps(payload, ensure_ascii=False),
                                 COMMON_SEGMENT_TOKENS, None,
                                 ctx + '%s %d-%d ' %
                                 (fname, chunk[0].get('_page'), chunk[-1].get('_page')))
                raw_items = data.get('pages') if isinstance(data, dict) else None
                if not isinstance(raw_items, list):
                    raise ValueError('边界模型未返回 pages 数组')
                returned = {}
                for item in raw_items:
                    if isinstance(item, dict):
                        try:
                            returned[int(item.get('page'))] = item
                        except (TypeError, ValueError):
                            pass
                for p in chunk:
                    page_no = int(p.get('_page', 0))
                    item = returned.get(page_no) or {}
                    anchor = _safe_int(item.get('anchor_page'))
                    allowed = set(active) | set(assignments.values()) | {page_no}
                    if anchor not in allowed or anchor > page_no:
                        anchor = _fallback_anchor(p, pages, assignments)
                    explicit_anchor = _matching_number_anchor(
                        p, item, pages, assignments)
                    if explicit_anchor is not None:
                        anchor = explicit_anchor
                    # 明确编号冲突时宁可拆开，避免高代价串单。
                    anchor_page = next((x for x in pages
                                        if int(x.get('_page', 0)) == anchor), None)
                    current_no = _clean(item.get('document_no')) or _clean(p.get('_document_no'))
                    anchor_no = _clean(anchor_page.get('_document_no')) if anchor_page else None
                    if (anchor != page_no and current_no and anchor_no and
                            _canonical(current_no) != _canonical(anchor_no)):
                        anchor = page_no
                        item['confidence'] = 'low'
                        item['reason'] = '原始文档编号冲突，已安全拆分'
                    _apply_segment_item(p, item, anchor)
                    assignments[page_no] = anchor
                    _touch_active(active, anchor, p)
            except Exception as e:
                message = '%s 第%s-%s页边界复核失败，已使用本地安全归组：%s' % (
                    fname, chunk[0].get('_page'), chunk[-1].get('_page'), str(e)[:180])
                issues.append({'document_id': '', 'field': '文档边界', 'message': message})
                for p in chunk:
                    page_no = int(p.get('_page', 0))
                    anchor = _fallback_anchor(p, pages, assignments)
                    _apply_segment_item(p, {'confidence': 'low', 'reason': 'AI边界复核失败，使用本地归组'},
                                        anchor)
                    p['_segment_error'] = str(e)[:180]
                    assignments[page_no] = anchor
                    _touch_active(active, anchor, p)
    return issues


def _segment_manifest(p, fields):
    values = {}
    for f in fields:
        if f['type'] == 'table':
            rows = p.get(f['key']) or []
            values[f['key']] = {'rows_on_page': len(rows),
                                'first_row': rows[0] if rows else None}
        else:
            value = p.get(f['key'])
            if value not in (None, ''):
                values[f['key']] = value
    return {
        'page': int(p.get('_page', 0)),
        'initial_document_type': p.get('_document_type') or '未知',
        'initial_document_no': p.get('_document_no'),
        'initial_page_role': p.get('_page_role') or 'unknown',
        'page_summary': p.get('_page_summary') or '',
        'identity_hints': p.get('_identity_hints') or [],
        'unified_field_values': values,
    }


def _fallback_anchor(page, pages, assignments):
    page_no = int(page.get('_page', 0))
    dtype = _canonical(page.get('_document_type') or '未知')
    doc_no = _canonical(page.get('_document_no'))
    previous = [p for p in pages if int(p.get('_page', 0)) < page_no]
    if doc_no:
        for prior in reversed(previous):
            if (_canonical(prior.get('_document_type') or '未知') == dtype and
                    _canonical(prior.get('_document_no')) == doc_no):
                return assignments.get(int(prior.get('_page', 0)),
                                       int(prior.get('_page', 0)))
    if page.get('_is_continuation'):
        for prior in reversed(previous):
            if _canonical(prior.get('_document_type') or '未知') == dtype:
                return assignments.get(int(prior.get('_page', 0)),
                                       int(prior.get('_page', 0)))
    return page_no


def _matching_number_anchor(page, item, pages, assignments):
    """完全相同的文档编号优先于模型的临时锚点，防止长距离交错页被拆开。"""
    page_no = int(page.get('_page', 0))
    dtype = _canonical(item.get('document_type') or page.get('_document_type') or '未知')
    doc_no = _canonical(item.get('document_no') or page.get('_document_no'))
    if not doc_no:
        return None
    for prior in reversed(pages):
        prior_no = int(prior.get('_page', 0))
        if prior_no >= page_no:
            continue
        if (_canonical(prior.get('_document_type') or '未知') == dtype and
                _canonical(prior.get('_document_no')) == doc_no):
            return assignments.get(prior_no, prior_no)
    return None


def _apply_segment_item(page, item, anchor):
    dtype = _clean(item.get('document_type'))
    doc_no = _clean(item.get('document_no'))
    if dtype:
        page['_document_type'] = dtype
    if doc_no:
        page['_document_no'] = doc_no
    page['_segment_anchor'] = int(anchor)
    page['_segment_confidence'] = (item.get('confidence')
                                   if item.get('confidence') in _CONF else 'low')
    page['_segment_reason'] = str(item.get('reason') or '').strip()[:240]


def _touch_active(active, anchor, page):
    active[anchor] = {
        'anchor_page': int(anchor),
        'last_seen_page': int(page.get('_page', 0)),
        'document_type': page.get('_document_type') or '未知',
        'document_no': page.get('_document_no'),
        'identity_hints': (page.get('_identity_hints') or [])[:4],
        'last_page_summary': page.get('_page_summary') or '',
    }
    active.move_to_end(anchor)
    while len(active) > max(1, COMMON_SEGMENT_ACTIVE):
        active.popitem(last=False)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def assemble_common_pages(page_results, fields, segmentation_issues=None):
    """按文件、AI 判断的类别和文档编号归组，支持不同类别页面交错出现。"""
    ordered = sorted([p for p in page_results if not p.get('_blank')],
                     key=lambda p: (str(p.get('_filename', '')), int(p.get('_page', 0))))
    groups, anchored, explicit, last_by_type = [], {}, {}, {}
    anon = 0
    for p in ordered:
        if p.get('_error'):
            groups.append([p])
            continue
        fname = str(p.get('_filename', ''))
        anchor = _safe_int(p.get('_segment_anchor'))
        if anchor is not None:
            akey = (fname, anchor)
            grp = anchored.get(akey)
            if grp is None:
                grp = []
                groups.append(grp)
                anchored[akey] = grp
            grp.append(p)
            continue
        dtype = str(p.get('_document_type') or '未知').strip() or '未知'
        tkey = (fname, _canonical(dtype))
        doc_no = _clean(p.get('_document_no'))
        ekey = (tkey, _canonical(doc_no)) if doc_no else None
        grp = explicit.get(ekey) if ekey else None
        if grp is None and p.get('_is_continuation'):
            grp = last_by_type.get(tkey)
        if grp is None:
            anon += 1
            grp = []
            groups.append(grp)
        grp.append(p)
        last_by_type[tkey] = grp
        if ekey:
            explicit[ekey] = grp

    records, issues = [], list(segmentation_issues or [])
    for i, grp in enumerate(groups, 1):
        rec, rec_issues = _fold_common(grp, fields, i)
        records.append(rec)
        issues.extend(rec_issues)
    return records, issues


def _fold_common(grp, fields, seq):
    first = grp[0]
    pages = '+'.join(str(p.get('_page', '')) for p in grp)
    if first.get('_error') and len(grp) == 1:
        rec = dict(first)
        rec.update(_pages=pages, _document_id='doc_%04d' % seq)
        return rec, [{'document_id': rec['_document_id'], 'field': '',
                      'message': str(first.get('_error'))}]
    rec = {
        '_document_id': 'doc_%04d' % seq,
        '_filename': first.get('_filename', ''), '_pages': pages,
        '_document_type': next((p.get('_document_type') for p in grp
                                if p.get('_document_type')), '未知'),
        '_document_no': next((p.get('_document_no') for p in grp
                              if p.get('_document_no')), None),
        '_evidence': '+'.join(OrderedDict.fromkeys(
            p.get('_evidence', '') for p in grp if p.get('_evidence'))),
        '_confidence': _min_conf([p.get('_confidence', '') for p in grp]),
        '_segmentation_confidence': _min_conf(
            [p.get('_segment_confidence', '') for p in grp]),
        '_segmentation_reason': '；'.join(OrderedDict.fromkeys(
            p.get('_segment_reason', '') for p in grp if p.get('_segment_reason'))),
        '_field_meta': {},
    }
    issues = []
    if rec['_segmentation_confidence'] == 'low':
        issues.append({'document_id': rec['_document_id'], 'field': '文档边界',
                       'message': rec['_segmentation_reason'] or '文档边界置信度较低'})
    for f in fields:
        if f['type'] == 'table':
            rows, source_pages, metas = [], [], []
            for p in grp:
                page_rows = p.get(f['key']) or []
                if page_rows:
                    rows.extend(page_rows)
                    source_pages.append(p.get('_page'))
                    metas.append((p.get('_field_meta') or {}).get(f['key'], {}))
            rec[f['key']] = rows
            rec['_field_meta'][f['key']] = {
                'source_label': next((m.get('source_label') for m in metas
                                      if m.get('source_label')), None),
                'evidence': '；'.join(OrderedDict.fromkeys(
                    m.get('evidence') for m in metas if m.get('evidence'))),
                'confidence': _min_conf([m.get('confidence', '') for m in metas]),
                'status': 'found' if rows else 'not_found',
                'source_page': '+'.join(str(x) for x in source_pages),
                'row_count': len(rows),
            }
            continue
        candidates = []
        for p in grp:
            value = p.get(f['key'])
            meta = (p.get('_field_meta') or {}).get(f['key'], {})
            if value not in (None, '') and meta.get('status') != 'not_applicable':
                candidates.append((value, meta, p.get('_page')))
        chosen, meta, conflict = _choose_candidate(candidates)
        rec[f['key']] = chosen
        rec['_field_meta'][f['key']] = meta
        if conflict:
            message = '多页候选值冲突：%s' % ' / '.join(str(x) for x in conflict[:5])
            rec['_field_meta'][f['key']]['status'] = 'ambiguous'
            issues.append({'document_id': rec['_document_id'], 'field': f['label'],
                           'message': message})
    return rec, issues


def _choose_candidate(candidates):
    if not candidates:
        return None, {'source_label': None, 'evidence': None, 'confidence': '',
                      'status': 'not_found', 'source_page': None}, []
    distinct = OrderedDict()
    for value, meta, page in candidates:
        distinct.setdefault(_value_key(value), []).append((value, meta, page))
    ranked = sorted(candidates,
                    key=lambda x: (_CONF.get(x[1].get('confidence'), -1), -int(x[2] or 0)),
                    reverse=True)
    value, source, page = ranked[0]
    meta = dict(source)
    meta['source_page'] = page
    conflict = [items[0][0] for items in distinct.values()] if len(distinct) > 1 else []
    return value, meta, conflict


def common_rows(records, fields):
    rows = []
    for rec in records:
        row = {k: rec.get(k) for k in ('_document_id', '_filename', '_pages',
                                       '_document_type', '_document_no', '_evidence',
                                       '_confidence', '_segmentation_confidence',
                                       '_segmentation_reason', '_error')}
        row['_field_meta'] = rec.get('_field_meta', {})
        row['_tables'] = {}
        for f in fields:
            row[f['key']] = rec.get(f['key'])
            if f['type'] == 'table':
                row['_tables'][f['key']] = rec.get(f['key']) or []
        rows.append(row)
    return rows


def _clean(value):
    if value in (None, '', 'null', 'None'):
        return None
    return str(value).strip()


def _canonical(value):
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', str(value or '').lower())


def _value_key(value):
    if isinstance(value, float):
        return ('number', round(value, 6))
    return ('value', _canonical(value))


def _min_conf(values):
    vals = [v for v in values if v in _CONF]
    return min(vals, key=lambda x: _CONF[x]) if vals else ''
