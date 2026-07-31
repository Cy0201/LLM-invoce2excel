# -*- coding: utf-8 -*-
"""
merge.py —— 字段规范化 + 跨页合并 + 本地算术校验  v7
相对旧版的关键改动：

  1. 列声明解析：description 里的「列：key 中文名, …」解析成 field['columns']，
     供提取提示词锁定键名、供行键重映射、供 sum_check 的列名（key 或中文名）解析。
  2. 续页感知合并：旧版按 group_key 值分桶，续页上没印单据编号就断链。
     v7 按文件内页序扫描：group_key 值出现且变化 → 开新记录；
     值缺失但模型判定 _is_continuation=true → 并入上一记录；
     没有 group_key 时也能靠 _is_continuation 链住多页合同/长发票。
  3. 行键重映射：模型偶尔用中文列名回行，按 columns 的 label→key 归一，
     保证跨页并表与求和列命中。
  4. 置信度取各页最小值（旧版取首页，续页识别差也看不出来）。
  5. 求和校验记录差额 diff，Excel/前端可直接展示差多少。
"""
import re
from collections import OrderedDict

_VALID_TYPES = {'text', 'number', 'date', 'checkbox', 'table', 'multiline'}
_CONF_ORDER = {'low': 0, 'medium': 1, 'high': 2}


# ══════════════════════════════════════════════════════════════
#  字段规范化
# ══════════════════════════════════════════════════════════════
def parse_columns(desc):
    """从「列：key1 中文1, key2 中文2」解析结构化列。容忍 中英混排/无key/各种分隔符。"""
    m = re.search(r'列\s*[:：]\s*(.+)$', desc or '', re.S)
    if not m:
        return []
    cols, seen = [], set()
    for i, seg in enumerate(re.split(r'[,，、;；\n]+', m.group(1))):
        seg = seg.strip().rstrip('。.')
        if not seg:
            continue
        km = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*[:：]?\s*(.*)$', seg)
        if km:
            key, label = km.group(1), (km.group(2).strip() or km.group(1))
        else:
            key, label = 'col%d' % (i + 1), seg
        if key in seen:
            key = '%s_%d' % (key, i + 1)
        seen.add(key)
        cols.append({'key': key, 'label': label})
    return cols


def normalize_fields(raw):
    out, seen = [], set()
    for i, f in enumerate(raw or []):
        if not isinstance(f, dict):
            continue
        key = re.sub(r'[^A-Za-z0-9_\u4e00-\u9fff]+', '_', str(f.get('key') or '').strip())
        key = key.strip('_') or 'field_%d' % (i + 1)
        if key in seen:
            key = '%s_%d' % (key, i + 1)
        seen.add(key)
        ftype = f.get('type') if f.get('type') in _VALID_TYPES else 'text'
        desc = str(f.get('description') or '').strip()
        fld = {
            'key': key,
            'label': str(f.get('label') or key).strip() or key,
            'type': ftype,
            'description': desc,
            'group_key': bool(f.get('group_key', False)),
            'carry': f.get('carry') if f.get('carry') in ('first', 'last') else 'first',
            'sum_check': f.get('sum_check') if isinstance(f.get('sum_check'), dict) else None,
            'columns': parse_columns(desc) if ftype == 'table' else [],
        }
        out.append(fld)
    _resolve_sum_checks(out)
    return out


def _resolve_sum_checks(fields):
    """sum_check 的 table/column 允许写 label，这里统一解析成 key。"""
    by_key = {f['key']: f for f in fields}
    by_label = {f['label']: f for f in fields}
    for f in fields:
        chk = f.get('sum_check')
        if not chk:
            continue
        tf = by_key.get(str(chk.get('table', ''))) or by_label.get(str(chk.get('table', '')))
        if not tf or tf['type'] != 'table':
            f['sum_check'] = None
            continue
        col = str(chk.get('column', '')).strip()
        hit = next((c for c in tf['columns'] if c['key'] == col), None) or \
              next((c for c in tf['columns'] if c['label'] == col), None)
        f['sum_check'] = {'table': tf['key'], 'column': (hit['key'] if hit else col)}


def remap_row(row, columns):
    """把模型可能用中文列名回的行，按 columns 归一成声明的 key。"""
    if not isinstance(row, dict):
        return None
    if not columns:
        return row
    label2key = {c['label']: c['key'] for c in columns}
    keys = {c['key'] for c in columns}
    out = {}
    for k, v in row.items():
        kk = k if k in keys else label2key.get(str(k).strip(), k)
        if kk not in out or out[kk] in (None, ''):
            out[kk] = v
    return out


# ══════════════════════════════════════════════════════════════
#  数值/置信度工具
# ══════════════════════════════════════════════════════════════
def to_num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if v in (None, ''):
        return None
    s = str(v).translate(str.maketrans('０１２３４５６７８９．，－', '0123456789.,-'))
    s = re.sub(r'[¥￥$,\s元]', '', s)
    try:
        return float(s)
    except ValueError:
        return None


def _min_conf(vals):
    got = [_CONF_ORDER[v] for v in vals if v in _CONF_ORDER]
    if not got:
        return ''
    return {0: 'low', 1: 'medium', 2: 'high'}[min(got)]


# ══════════════════════════════════════════════════════════════
#  跨页合并（续页感知）
# ══════════════════════════════════════════════════════════════
def merge_pages(page_results, fields):
    """page_results: [{'_page','_filename','_kind','_evidence', 字段…}]
       返回 (records, validations)。空白页(_blank)丢弃；错误页(_error)独立成条且不打断分组链。"""
    group_field = next((f['key'] for f in fields if f.get('group_key')), None)
    scalars = [f for f in fields if f['type'] != 'table']
    tables = [f for f in fields if f['type'] == 'table']

    ordered = sorted([p for p in page_results if not p.get('_blank')],
                     key=lambda p: (str(p.get('_filename', '')), int(p.get('_page', 0))))

    groups, cur, cur_file, cur_gid = [], None, None, None
    for p in ordered:
        fn = p.get('_filename', '')
        if p.get('_error'):
            groups.append([p])                       # 错误页独立成条
            continue                                 # 不打断当前分组链
        gid = p.get(group_field) if group_field else None
        gid = None if gid in (None, '') else str(gid)
        cont = bool(p.get('_is_continuation'))
        if cur is None or fn != cur_file:
            new = True
        elif group_field:
            new = (gid != cur_gid) if gid is not None else (not cont)
        else:
            new = not cont
        if new:
            cur = [p]
            groups.append(cur)
            cur_file, cur_gid = fn, gid
        else:
            cur.append(p)
            if gid is not None:
                cur_gid = gid

    records, validations = [], []
    for grp in groups:
        rec = _fold(grp, scalars, tables)
        _apply_sum_checks(rec, scalars, validations)
        records.append(rec)
    return records, validations


def _fold(grp, scalars, tables):
    pages = '+'.join(str(g.get('_page', '')) for g in grp)
    first = grp[0]
    if first.get('_error') and len(grp) == 1:
        rec = dict(first)
        rec['_pages'] = pages
        return rec
    rec = {'_filename': first.get('_filename', ''), '_pages': pages,
           '_evidence': '+'.join(OrderedDict.fromkeys(
               g.get('_evidence', '') for g in grp if g.get('_evidence'))),
           '_confidence': _min_conf([g.get('_confidence', '') for g in grp]),
           '_kinds': [g.get('_kind', '') for g in grp]}
    if any(g.get('_repaired') for g in grp):
        rec['_repaired'] = True
    for f in scalars:
        vals = [g.get(f['key']) for g in grp if g.get(f['key']) not in (None, '', [])]
        rec[f['key']] = (vals[-1] if f['carry'] == 'last' else vals[0]) if vals else None
    for tf in tables:
        rows = []
        for g in grp:
            v = g.get(tf['key'])
            if isinstance(v, list):
                for r in v:
                    rr = remap_row(r, tf['columns'])
                    if rr:
                        rows.append(rr)
        rec[tf['key']] = rows
    return rec


def _apply_sum_checks(rec, scalars, validations):
    if rec.get('_error'):
        return
    for sf in scalars:
        chk = sf.get('sum_check')
        if not chk:
            continue
        rows = rec.get(chk['table']) or []
        total, ok = 0.0, True
        for r in rows:
            n = to_num(r.get(chk['column'])) if isinstance(r, dict) else None
            if n is None:
                ok = False
            else:
                total += n
        total = round(total, 2)
        declared = to_num(rec.get(sf['key']))
        match = bool(ok and rows and declared is not None
                     and abs(declared - total) < 0.011)
        diff = (None if declared is None else round(declared - total, 2))
        rec['_check_%s' % sf['key']] = match
        validations.append({
            'file': rec.get('_filename', ''), 'group_id': rec.get('_pages', ''),
            'pages': rec.get('_pages', ''), 'field': sf['key'], 'label': sf['label'],
            'table': chk['table'], 'column': chk['column'],
            'sum_from_table': total, 'declared': declared, 'diff': diff,
            'match': match, 'repaired': bool(rec.get('_repaired'))})


def splice_results(all_pages, repaired_pages):
    """把复核后的页结果替换回全量页结果（按 文件名+页码 定位）。"""
    idx = {(p.get('_filename'), p.get('_page')): p for p in repaired_pages}
    return [idx.get((p.get('_filename'), p.get('_page')), p) for p in all_pages]
