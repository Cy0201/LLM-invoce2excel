# -*- coding: utf-8 -*-
"""混合异构文档流程的纯数据层。

它与 common_mode 的“跨版式统一字段”不同：先按页面和逻辑文档类型拆分，
再为每种文档分别建立字段方案。不同类型的专有字段不会被公共字段归纳过程丢掉。
"""
from collections import OrderedDict

import common_mode as CM


def page_from_inventory(item, *, filename, page_no, kind, pf=None, idx=None):
    """把单页观察结果转换为边界复核可用的页记录。"""
    item = item if isinstance(item, dict) else {}
    role = item.get('page_role') if item.get('page_role') in (
        'first', 'continuation', 'single', 'unknown') else 'unknown'
    dtype = str(item.get('document_type') or '未知').strip() or '未知'
    return {
        '_filename': filename, '_page': int(page_no), '_kind': kind,
        '_document_type': dtype, '_document_no': CM._clean(item.get('document_no')),
        '_page_role': role, '_is_continuation': role == 'continuation',
        '_page_summary': str(item.get('page_summary') or '').strip()[:240],
        '_identity_hints': CM._normalize_identity_hints(item.get('identity_hints')),
        '_confidence': item.get('confidence') if item.get('confidence') in CM._CONF else '',
        '_inventory': dict(item), '_source_pf': pf, '_source_idx': idx,
    }


def discover_type_schemas(ai_call, pages, ctx='[按类型字段总结] '):
    """按 AI 识别的文档类型分别总结字段；同一类型内部允许不同版式。"""
    buckets = OrderedDict()
    display = {}
    for page in pages:
        if page.get('_blank') or page.get('_error'):
            continue
        dtype = str(page.get('_document_type') or '未知').strip() or '未知'
        key = CM._canonical(dtype) or '未知'
        display.setdefault(key, dtype)
        inv = dict(page.get('_inventory') or {})
        inv['document_type'] = dtype
        inv['_source'] = {'filename': page.get('_filename'),
                          'page': page.get('_page'),
                          'document_no': page.get('_document_no')}
        buckets.setdefault(key, []).append(inv)
    schemas = []
    for key, inventories in buckets.items():
        result = CM.discover_from_inventories(
            ai_call, inventories, ctx + '《%s》 ' % display[key])
        schemas.append({
            'document_type': display[key],
            'document_types': result.get('document_types') or [display[key]],
            'summary': result.get('summary', ''),
            'fields': result.get('fields') or [],
            'sampled_pages': len(inventories),
        })
    return schemas


def schema_for(schemas, dtype):
    key = CM._canonical(dtype) or '未知'
    for schema in schemas:
        if CM._canonical(schema.get('document_type')) == key:
            return schema
    return None


def assemble_pages(page_results, schemas, segmentation_issues=None):
    """按边界锚点分组，每个逻辑文档使用自己类型的字段方案。"""
    ordered = sorted([p for p in page_results if not p.get('_blank')],
                     key=lambda p: (str(p.get('_filename', '')),
                                   int(p.get('_page', 0))))
    groups, keys = OrderedDict(), {}
    for page in ordered:
        if page.get('_error'):
            key = ('error', page.get('_filename'), page.get('_page'))
        else:
            anchor = CM._safe_int(page.get('_segment_anchor'))
            key = (str(page.get('_filename', '')), anchor or page.get('_page'))
        groups.setdefault(key, []).append(page)

    records, issues = [], list(segmentation_issues or [])
    # 先按来源页排序，确保文档 ID 和用户看到的顺序稳定。
    group_items = sorted(groups.items(), key=lambda kv: (
        str(kv[1][0].get('_filename', '')), int(kv[1][0].get('_page', 0))))
    for seq, (_key, grp) in enumerate(group_items, 1):
        dtype = next((p.get('_document_type') for p in grp
                      if p.get('_document_type')), '未知')
        schema = schema_for(schemas, dtype) or {'document_type': dtype, 'fields': []}
        rec, rec_issues = CM._fold_common(grp, schema.get('fields') or [], seq)
        rec['_schema_type'] = schema.get('document_type') or dtype
        rec['_schema_summary'] = schema.get('summary', '')
        rec['_field_keys'] = [f['key'] for f in schema.get('fields') or []]
        old_id = rec.get('_document_id')
        rec['_document_id'] = 'mix_doc_%04d' % seq
        for issue in rec_issues:
            issue['document_id'] = rec['_document_id']
        records.append(rec)
        issues.extend(rec_issues)
    return records, issues


def rows(records, schemas):
    """返回前端可序列化的类型化记录。"""
    out = []
    for rec in records:
        row = {k: v for k, v in rec.items()
               if not str(k).startswith('_source') and k != '_inventory'}
        row['_tables'] = {}
        schema = schema_for(schemas, rec.get('_schema_type')) or {'fields': []}
        for field in schema.get('fields') or []:
            if field.get('type') == 'table':
                row['_tables'][field['key']] = rec.get(field['key']) or []
        out.append(row)
    return out

