# -*- coding: utf-8 -*-
"""
extractor.py —— 字段驱动的单页提取引擎  v7
相对旧版的关键改动：

  1. 单页一次请求（标量+表格合并）：请求数直接减半，且合计与明细出自同一次
     生成，算术自洽率显著更高。max_tokens 按证据规模动态估算。
  2. 失败阶梯（任何一份票据都走得通）：
       合并请求
        ├─ stop_reason=max_tokens → 升额到硬上限重试一次（旧版直接吞掉截断）
        ├─ JSON 解析失败 → 携"上次输出不可解析"提醒重试一次
        ├─ 仍失败且含表格 → 拆分模式（标量一请求 + 每表一请求）兜底
        └─ 视觉请求遇到"网关不支持图片" → 自动降级为 OCR/嵌入文本路线
  3. 严格输出契约：显式 JSON 骨架 + 列 key 白名单 + 逐字照抄/禁止编造规则
     + 续页语义（_is_continuation）+ 页级置信度。
  4. 数值/日期本地归一：全角转半角、剥货币符与千分位、多格式日期转 ISO——
     这些确定性工作不交给模型，省 token 也更稳。
"""
import os
import re
import json
import logging

from ai_client import robust_call, parse_json, AIResponseError
from merge import to_num

logger = logging.getLogger('extractor')

MAX_TOKENS_CAP = int(os.environ.get('MAX_TOKENS_CAP', '1638400'))
HARD_TOKENS_CAP = int(os.environ.get('HARD_TOKENS_CAP', '3276800'))

_TYPE_TOKEN = {
    'text': '"字符串"或null',
    'number': '数字或null',
    'date': '"YYYY-MM-DD"或null',
    'checkbox': 'true|false|null',
    'multiline': '"多行字符串(\\n分隔)"或null',
}


# ══════════════════════════════════════════════════════════════
#  提示词构造
# ══════════════════════════════════════════════════════════════
def build_system(fields):
    scalars = [f for f in fields if f['type'] != 'table']
    tables = [f for f in fields if f['type'] == 'table']
    L = ["你是严谨的票据/文档结构化提取引擎。从给定的单页证据（保留版式的PDF文本层，"
         "或扫描图片，可能附带OCR辅助文本）中，按字段定义提取数据，只输出一个 JSON 对象，"
         "不要 markdown、不要解释。", "", "# 字段定义"]
    for f in scalars:
        L.append("- %s (%s) %s%s" % (f['key'], f['type'], f['label'],
                                     '：%s' % f['description'] if f['description'] else ''))
    for tf in tables:
        L.append("- %s (table) %s：每行一个对象，列固定如下（键名必须完全一致）" %
                 (tf['key'], tf['label']))
        if tf['columns']:
            for c in tf['columns']:
                L.append("    · %s ＝ %s" % (c['key'], c['label']))
        else:
            L.append("    · 列名自拟：用简短英文snake_case作键，同一列在所有页保持同名")
    L += ["", "# 输出JSON骨架（键必须齐全，顺序不限）", "{"]
    for f in scalars:
        L.append('  "%s": %s,' % (f['key'], _TYPE_TOKEN.get(f['type'], '"字符串"或null')))
    for tf in tables:
        cols = ', '.join('"%s": …' % c['key'] for c in tf['columns'][:8]) or '…'
        L.append('  "%s": [ {%s}, … ] 或 [],' % (tf['key'], cols))
    L += ['  "_is_continuation": true|false,',
          '  "_confidence": "high"|"medium"|"low"',
          '}', '',
          "# 提取规则",
          "1. 逐字取自证据原文，绝不编造、猜测或凭常识补全；证据中找不到 → null（表格找不到 → []）。",
          "2. number：只输出数字（可含小数点与负号）。去掉货币符号、单位、千分位逗号；全角数字视同半角。",
          "3. date：一律转成 YYYY-MM-DD（如 2026年7月3日 → 2026-07-03）。",
          "4. table：不遗漏任何一行、不重复行；表头行、小计/合计行不算数据行；某格无值填 null。",
          "5. 版式文本中同一行内被多个连续空格分开的内容，通常是表格的不同列；"
          "个别相邻列因数值较宽可能只剩1个空格，请结合列含义正确切分，"
          "不要把两个单元格并成一个。",
          "6. _is_continuation：本页若没有新单据的抬头/编号、只是上一页明细的延续（续页），"
          "填 true，此时抬头类字段可为 null；否则填 false。",
          "7. _confidence：证据清晰、各字段可靠 → high；个别字符存疑 → medium；"
          "大面积模糊或结构混乱 → low。",
          "8. 只输出 JSON 本身。"]
    return '\n'.join(L)


def build_user(kind, fname, page_no, total, text='', ocr_hint='',
               repair_note='', with_image=False):
    if kind == 'native':
        src = 'PDF文本层(版式保留)' + ('，另附本页图像供交叉核对' if with_image else '')
    else:
        src = '扫描图片' if with_image else '扫描页OCR文本'
    parts = ["【证据 · 文件《%s》第 %d/%d 页 · %s】" % (fname, page_no, total, src)]
    if kind == 'native' and text:
        parts.append(text)
    else:
        if text:
            parts.append("【该页自带的低质量文本层(仅供参考%s)】\n%s"
                         % ('，以图片为准' if with_image else '', text[:800]))
        if ocr_hint:
            parts.append("【OCR辅助文本(可能有误%s)】\n%s"
                         % ('，以图片为准' if with_image else '', ocr_hint))
    if repair_note:
        parts.append("【复核要求】\n" + repair_note)
    parts.append("请输出 JSON：")
    return '\n\n'.join(parts)


def est_max_tokens(fields, evidence, assume_rows=None):
    scalars = sum(1 for f in fields if f['type'] != 'table')
    cols = sum(max(4, len(f['columns'])) for f in fields if f['type'] == 'table')
    if evidence:
        digit_lines = sum(1 for ln in evidence.split('\n')
                          if len(re.findall(r'\d', ln)) >= 2)
        rows_est = max(4, digit_lines)
    else:
        rows_est = assume_rows or 30      # 纯视觉页看不见文本，按较密页面假定
    est = 700 + 40 * scalars + (rows_est * (15 + 14 * cols) if cols else 0)
    return max(1638400, min(MAX_TOKENS_CAP, est))


# ══════════════════════════════════════════════════════════════
#  本地归一
# ══════════════════════════════════════════════════════════════
_DATE_PATS = [
    re.compile(r'(\d{4})\s*[年/\.\-]\s*(\d{1,2})\s*[月/\.\-]\s*(\d{1,2})\s*日?'),
]
_FW = str.maketrans('０１２３４５６７８９．－／', '0123456789.-/')


def norm_date(v):
    if v in (None, ''):
        return None
    s = str(v).translate(_FW).strip()
    for pat in _DATE_PATS:
        m = pat.search(s)
        if m:
            return '%04d-%02d-%02d' % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return s


def coerce(value, ftype):
    if value in (None, '', 'null', 'None'):
        return None
    if ftype == 'number':
        n = to_num(value)
        return value if n is None else n
    if ftype == 'date':
        return norm_date(value)
    if ftype == 'checkbox':
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ('true', '是', 'yes', 'y', '1', '✓', '√')
    if isinstance(value, str):
        return value.strip()
    return value


# ══════════════════════════════════════════════════════════════
#  请求阶梯
# ══════════════════════════════════════════════════════════════
_JSON_REMIND = ("\n\n（注意：你上一次的输出无法解析为 JSON。"
                "请重新输出，且只输出一个合法的 JSON 对象，别无其他内容。）")


def _ask_json(ai_call, kind_tag, system, user, max_tokens, image_b64, ctx):
    """一次带全套容错的问答：网络重试 → 截断升额 → JSON提醒重试。"""
    def _once(u, mt):
        return robust_call(lambda: ai_call(kind_tag, system, u, mt, image_b64=image_b64),
                           ctx=ctx)

    text, stop = _once(user, max_tokens)
    if stop == 'max_tokens' and max_tokens < HARD_TOKENS_CAP:
        logger.info('%s输出被截断(max_tokens=%d)，升额到 %d 重试',
                    ctx, max_tokens, HARD_TOKENS_CAP)
        text, stop = _once(user, HARD_TOKENS_CAP)
    try:
        return parse_json(text)
    except ValueError:
        logger.info('%sJSON 解析失败，携提醒重试一次', ctx)
        text, _ = _once(user + _JSON_REMIND, max(max_tokens, 6553600))
        return parse_json(text)


def extract_page(fields, ai_call, *, kind, fname, page_no, total,
                 text='', image_b64=None, ocr_hint='', caps=None,
                 repair_note='', ctx=''):
    """提取一页。返回 {字段…, _is_continuation, _confidence, _evidence, _kind}。
    caps：跨页共享的运行时能力表（如 {'vision': True}），发现网关无视觉后
    整个任务自动改走 OCR 文本路线，不再逐页撞墙。"""
    caps = caps if caps is not None else {}
    use_vision = bool(image_b64) and caps.get('vision', True)
    text_evidence = text if kind == 'native' else (ocr_hint or text)
    system = build_system(fields)

    def _run(with_image):
        user = build_user(kind, fname, page_no, total, text=text, ocr_hint=ocr_hint,
                          repair_note=repair_note, with_image=with_image)
        mt = est_max_tokens(fields, text_evidence)
        try:
            return _ask_json(ai_call, 'vision' if with_image else 'text',
                             system, user, mt, image_b64 if with_image else None, ctx)
        except (ValueError, AIResponseError) as e:
            if isinstance(e, AIResponseError) and e.no_vision:
                raise
            tables = [f for f in fields if f['type'] == 'table']
            if not tables:
                raise
            logger.info('%s合并请求失败(%s)，改用拆分模式兜底', ctx, e)
            return _split_extract(fields, ai_call, user, with_image, image_b64,
                                  text_evidence, ctx)

    try:
        data = _run(use_vision)
    except AIResponseError as e:
        if e.no_vision and use_vision:
            caps['vision'] = False
            logger.warning('%s网关不支持视觉，本任务改走 OCR/文本路线', ctx)
            if text_evidence:
                data = _run(False)
                data['__forced_text'] = True
            else:
                raise AIResponseError(
                    str(e) + '（该页无任何文字线索：未安装本地OCR且页面无文本层，无法提取）',
                    no_vision=True)
        else:
            raise

    out = {}
    for f in fields:
        if f['type'] == 'table':
            rows = data.get(f['key'])
            if not isinstance(rows, list):
                rows = data.get('items') if isinstance(data.get('items'), list) else []
            out[f['key']] = [r for r in rows if isinstance(r, dict)]
        else:
            out[f['key']] = coerce(data.get(f['key']), f['type'])
    out['_is_continuation'] = bool(data.get('_is_continuation'))
    out['_confidence'] = data.get('_confidence') if data.get('_confidence') in (
        'high', 'medium', 'low') else ''
    if data.get('__forced_text'):
        out['_evidence'] = 'ocr_text'
    elif kind == 'native':
        out['_evidence'] = 'native_text'
    else:
        out['_evidence'] = 'vision' if use_vision and caps.get('vision', True) else 'ocr_text'
    out['_kind'] = kind
    if repair_note:
        out['_repaired'] = True
    return out


def _split_extract(fields, ai_call, user, with_image, image_b64, text_evidence, ctx):
    """兜底拆分：标量一次 + 每张表一次。"""
    scalars = [f for f in fields if f['type'] != 'table']
    tables = [f for f in fields if f['type'] == 'table']
    data = {}
    if scalars:
        meta = [{'key': '_is_continuation', 'label': '是否续页', 'type': 'checkbox',
                 'description': '本页无新单据抬头、仅是上一页延续时为true', 'columns': []},
                {'key': '_confidence', 'label': '置信度', 'type': 'text',
                 'description': 'high/medium/low 三选一', 'columns': []}]
        sys_s = build_system(scalars + meta)
        data.update(_ask_json(ai_call, 'vision' if with_image else 'text', sys_s,
                              user, 6553600, image_b64 if with_image else None,
                              ctx + '[拆分·标量] '))
    for tf in tables:
        sys_t = build_system([tf])
        mt = max(3276800, min(HARD_TOKENS_CAP, est_max_tokens([tf], text_evidence) * 2))
        try:
            td = _ask_json(ai_call, 'vision' if with_image else 'text', sys_t,
                           user, mt, image_b64 if with_image else None,
                           ctx + '[拆分·%s] ' % tf['label'])
            rows = td.get(tf['key'])
            if not isinstance(rows, list):
                rows = td.get('items') if isinstance(td.get('items'), list) else []
            data[tf['key']] = rows
        except Exception as e:
            logger.warning('%s表「%s」拆分提取仍失败: %s', ctx, tf['label'], e)
            data[tf['key']] = []
    return data


# ══════════════════════════════════════════════════════════════
#  复核提示（供 app 的自动复核回路使用）
# ══════════════════════════════════════════════════════════════
def repair_note_for(issues):
    L = ["此前对这份单据的提取存在算术不一致，需要你重点复核："]
    for v in issues:
        L.append("· 字段「%s」提取值为 %s，但明细表 %s 的 %s 列逐行求和为 %s（差 %s）。"
                 % (v['label'], v['declared'], v.get('table', ''),
                    v.get('column', ''), v['sum_from_table'], v.get('diff')))
    L.append("请逐行重新核对该列每个数字与合计值本身，特别注意易混字符"
             "（0/8、1/7、5/6、3/8）与小数点位置、千分位；若上次多读/漏读了行，请纠正。"
             "核对后按同样的 JSON 骨架完整输出本页全部字段。")
    return '\n'.join(L)
