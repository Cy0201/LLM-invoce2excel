# -*- coding: utf-8 -*-
"""
claude_sim.py —— 离线测试用的"称职 AI"仿真器  v7
不联网时验证除真实模型外的全链路（selftest.py 使用）。

与旧版 mock_ai 的本质区别：旧版把某一家公司名、某一种行格式写死在正则里，
只对一份样本"假装通过"。本仿真器按 extractor 真实的提示词契约工作——
从 system 里解析字段定义与表格列，从 user 里定位证据文本，
用通用启发式提取，因此换任何样本文档都成立，测的是真实链路。

支持故障注入（验证提取阶梯的每一级）：
  pages_bad_json  : 这些页第一次返回带废话的坏 JSON → 触发"提醒重试"
  pages_truncate  : 这些页在低额度下返回 stop_reason=max_tokens → 触发"升额重试"
  wrong_scalar    : {(文件,页): (字段key, 偏差)} 首次提取该字段值加偏差
                    → 触发 sum_check 不一致 → 自动复核 →（携复核要求时）返回正确值
  no_vision       : 模拟无视觉能力的网关（带图请求抛 no_vision）→ 触发 OCR 降级
"""
import re
import json

from ai_client import AIResponseError

_HARD_CAP = 32768


class SimAI(object):
    def __init__(self, pages_bad_json=None, pages_truncate=None,
                 wrong_scalar=None, no_vision=False):
        self.pages_bad_json = set(pages_bad_json or [])
        self.pages_truncate = set(pages_truncate or [])
        self.wrong_scalar = dict(wrong_scalar or {})
        self.no_vision = no_vision
        self.calls = []                      # (kind, page_key, max_tokens) 审计用

    # ── 入口：与 AIClient.call 同签名 ─────────────────────────
    def __call__(self, kind, system, user, max_tokens, image_b64=None):
        page_key = _page_key(user)
        self.calls.append((kind, page_key, int(max_tokens)))
        if '回显器' in system:
            return 'OK', 'end_turn'
        if system.startswith('你是文档提取助手'):
            return '右上角编号栏', 'end_turn'
        if self.no_vision and kind == 'vision' and image_b64:
            raise AIResponseError('带图片的请求返回了空 content——模拟无视觉网关',
                                  no_vision=True)
        if system.startswith('你是票据/文档结构分析引擎'):
            return self._analyze(), 'end_turn'
        return self._extract(system, user, int(max_tokens), page_key)

    # ── 分析 ─────────────────────────────────────────────────
    @staticmethod
    def _analyze():
        from presets import PRESETS
        return json.dumps({'doc_type': '报关税票/缴款书',
                           'fields': PRESETS['报关税票/缴款书']},
                          ensure_ascii=False)

    # ── 提取 ─────────────────────────────────────────────────
    def _extract(self, system, user, max_tokens, page_key):
        scalars, tables = _parse_fields(system)
        evidence = _evidence_text(user)
        repairing = '【复核要求】' in user
        reminded = '无法解析为 JSON' in user

        out = {}
        for key, ftype, label in scalars:
            out[key] = _find_scalar(evidence, label, ftype)
        for key, cols in tables:
            out[key] = _find_rows(evidence, cols)
        if scalars and not any(k == '_is_continuation' for k, _, _ in scalars):
            out['_is_continuation'] = bool(re.search(r'续', evidence[:150]))
            out['_confidence'] = 'high'

        # 故障注入：错值（复核前）
        if not repairing and page_key in self.wrong_scalar:
            fkey, delta = self.wrong_scalar[page_key]
            if isinstance(out.get(fkey), (int, float)):
                out[fkey] = round(out[fkey] + delta, 2)

        payload = json.dumps(out, ensure_ascii=False)

        # 故障注入：坏 JSON（提醒后恢复）
        if page_key in self.pages_bad_json and not reminded and not repairing:
            return '好的，下面是提取结果：\n```json\n' + payload[:40], 'end_turn'
        # 故障注入：截断（升额后恢复）
        if page_key in self.pages_truncate and max_tokens < _HARD_CAP and not repairing:
            return payload[:len(payload) // 2], 'max_tokens'
        return payload, 'end_turn'


# ══════════════════════════════════════════════════════════════
#  契约解析（与 extractor.build_system / build_user 对应）
# ══════════════════════════════════════════════════════════════
def _page_key(user):
    m = re.search(r'《(.+?)》第\s*(\d+)/', user or '')
    return (m.group(1), int(m.group(2))) if m else ('', 0)


def _parse_fields(system):
    scalars, tables, cur_table = [], [], None
    for ln in system.split('\n'):
        m = re.match(r'^- (\w+) \((\w+)\) ([^：:]+)', ln)
        if m:
            key, ftype, label = m.group(1), m.group(2), m.group(3).strip()
            if ftype == 'table':
                cur_table = (key, [])
                tables.append(cur_table)
            else:
                scalars.append((key, ftype, label))
                cur_table = None
            continue
        cm = re.match(r'^\s+·\s+(\w+)\s*＝\s*(.+)$', ln)
        if cm and cur_table is not None:
            cur_table[1].append((cm.group(1), cm.group(2).strip()))
    return scalars, tables


def _evidence_text(user):
    body = re.split(r'【证据[^】]*】\s*', user, maxsplit=1)
    text = body[1] if len(body) > 1 else user
    text = re.split(r'【复核要求】', text)[0]
    text = re.sub(r'【[^】]*】', '', text)
    return text.replace('请输出 JSON：', '').strip()


_CH_EQ = {'(': '[（(]', ')': '[）)]', '（': '[（(]', '）': '[）)]',
          '¥': '[¥￥]', '￥': '[¥￥]', ':': '[:：]', '：': '[:：]'}


def _label_pat(label):
    return ''.join(_CH_EQ.get(ch, re.escape(ch)) for ch in label)


def _find_scalar(text, label, ftype):
    lab = _label_pat(label)
    pats = [lab + r'\s*[:：]\s*', lab + r'\s+']
    for p in pats:
        m = re.search(p + r'([^\n]{1,60})', text)
        if not m:
            continue
        raw = re.split(r'\s{2,}', m.group(1).strip())[0].strip()
        if not raw:
            continue
        if ftype == 'number':
            nm = re.search(r'-?[\d,，]+(?:\.\d+)?', raw)
            if nm:
                return float(nm.group(0).replace(',', '').replace('，', ''))
            continue
        return raw
    return None


def _find_rows(text, cols):
    n = len(cols)
    labels = [c[1] for c in cols]
    rows = []
    for ln in text.split('\n'):
        parts = [p for p in re.split(r'\s{2,}', ln.strip()) if p]
        # 列间隙偶尔只有1个空格（宽值挤占）：像真实模型一样按"数字|文字"语义再切分
        while len(parts) < n:
            for i, p in enumerate(parts):
                m = re.match(r'^([\d,，.\-]+)\s+(\S.*)$', p)
                if m:
                    parts[i:i + 1] = [m.group(1), m.group(2)]
                    break
            else:
                break
        if len(parts) < max(2, n - 2):
            continue
        if sum(1 for lb in labels if lb in ln) >= 2:
            continue                                   # 表头行
        if not re.search(r'\d', ln):
            continue
        if re.match(r'^\s*合计', ln):
            continue                                   # 合计行不算数据行
        row = {}
        for i, (key, _lb) in enumerate(cols):
            row[key] = parts[i] if i < len(parts) else None
        rows.append(row)
    return rows
