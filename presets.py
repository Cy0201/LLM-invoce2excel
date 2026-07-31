# -*- coding: utf-8 -*-
"""
presets.py —— 预设字段库 + AI 分析/补全提示词  v7
字段三个可选标记（决定合并与校验，与旧版兼容）：
  group_key : true → 该字段值相同的连续页合并成一条逻辑记录
  carry     : 'first'/'last' → 合并取值策略（合计类常在末页，用 last）
  sum_check : {"table": 表格key, "column": 列key} → 本字段 = 该列求和，本地零AI校验

表格列声明约定（v7 规范化）：description 里写「列：key1 中文名1, key2 中文名2, …」，
merge.normalize_fields 会解析成结构化 columns，提取提示词据此锁定键名，
保证跨页/跨文件键名一致（这是合并与求和校验能稳定工作的前提）。
"""

PRESETS = {
    "报关税票/缴款书": [
        {"key": "customs_office", "label": "关别", "type": "text",
         "description": "标题栏的海关名称，如「深圳海关」"},
        {"key": "issue_date", "label": "填发日期", "type": "date",
         "description": "填发日期，输出YYYY-MM-DD"},
        {"key": "bill_no", "label": "号码", "type": "text",
         "description": "右上角 No. 后的编号"},
        {"key": "declaration_no", "label": "报关单编号", "type": "text",
         "description": "18位报关单号", "group_key": True},
        {"key": "payer_name", "label": "缴款单位", "type": "text",
         "description": "缴款单位名称"},
        {"key": "total_amount", "label": "合计(¥)", "type": "number",
         "description": "合计小写金额", "carry": "last",
         "sum_check": {"table": "goods_table", "column": "tax_amount"}},
        {"key": "goods_table", "label": "货物明细", "type": "table",
         "description": "列：seq 序号, hs_code 税号, name 货物名称, quantity 数量, "
                        "unit 单位, price 完税价格, rate 税率, tax_amount 税款金额"},
    ],
    "增值税发票": [
        {"key": "invoice_no", "label": "发票号码", "type": "text",
         "description": "发票号码（数电票为20位）", "group_key": True},
        {"key": "invoice_date", "label": "开票日期", "type": "date",
         "description": "开票日期，输出YYYY-MM-DD"},
        {"key": "buyer", "label": "购买方", "type": "text",
         "description": "购买方名称"},
        {"key": "seller", "label": "销售方", "type": "text",
         "description": "销售方名称"},
        {"key": "items_table", "label": "开票明细", "type": "table",
         "description": "列：name 项目名称, spec 规格型号, unit 单位, quantity 数量, "
                        "price 单价, amount 金额, tax_rate 税率, tax 税额"},
        {"key": "total_amount", "label": "合计金额", "type": "number",
         "description": "不含税合计金额", "carry": "last",
         "sum_check": {"table": "items_table", "column": "amount"}},
        {"key": "total_tax", "label": "合计税额", "type": "number",
         "description": "税额合计", "carry": "last",
         "sum_check": {"table": "items_table", "column": "tax"}},
        {"key": "grand_total", "label": "价税合计", "type": "number",
         "description": "价税合计小写金额", "carry": "last"},
    ],
    "送货单": [
        {"key": "delivery_no", "label": "送货单号", "type": "text",
         "description": "单据编号，通常在右上角", "group_key": True},
        {"key": "date", "label": "送货日期", "type": "date",
         "description": "输出YYYY-MM-DD"},
        {"key": "supplier", "label": "供应商", "type": "text", "description": "送货单位"},
        {"key": "receiver", "label": "收货单位", "type": "text", "description": "收货单位全称"},
        {"key": "items_table", "label": "送货明细", "type": "table",
         "description": "列：seq 序号, name 品名, spec 规格, unit 单位, "
                        "quantity 数量, remark 备注"},
        {"key": "total_qty", "label": "总数量", "type": "number",
         "description": "数量合计", "carry": "last",
         "sum_check": {"table": "items_table", "column": "quantity"}},
    ],
    "合同": [
        {"key": "contract_no", "label": "合同编号", "type": "text",
         "description": "合同编号/代号", "group_key": True},
        {"key": "sign_date", "label": "签订日期", "type": "date",
         "description": "输出YYYY-MM-DD"},
        {"key": "party_a", "label": "甲方", "type": "text", "description": "合同甲方名称"},
        {"key": "party_b", "label": "乙方", "type": "text", "description": "合同乙方名称"},
        {"key": "contract_amount", "label": "合同金额", "type": "number",
         "description": "合同总金额小写"},
        {"key": "term", "label": "合同期限", "type": "text", "description": "有效期/履行期限"},
        {"key": "signing_location", "label": "签订地点", "type": "text",
         "description": "合同签署地点"},
    ],
    "通用表单": [
        {"key": "form_no", "label": "表单编号", "type": "text", "description": "编号或流水号"},
        {"key": "submit_date", "label": "提交日期", "type": "date",
         "description": "输出YYYY-MM-DD"},
        {"key": "applicant", "label": "申请人", "type": "text", "description": "填写人/申请人"},
        {"key": "department", "label": "所属部门", "type": "text", "description": "所在部门"},
        {"key": "request_type", "label": "申请事项", "type": "text", "description": "申请类别"},
        {"key": "amount", "label": "申请金额", "type": "number", "description": "如涉及金额"},
        {"key": "remarks", "label": "备注", "type": "multiline", "description": "备注或补充说明"},
        {"key": "approvals", "label": "审批意见", "type": "table",
         "description": "列：step 审批环节, approver 审批人, opinion 审批意见, date 日期"},
    ],
}

DEFAULT_FIELDS = PRESETS["通用表单"]


# ══════════════════════════════════════════════════════════════
#  AI-1 文档分析：识别类型 + 推荐字段（严格 JSON 契约）
# ══════════════════════════════════════════════════════════════
ANALYZE_SYSTEM = (
    "你是票据/文档结构分析引擎。任务：根据给定的文档证据（版式文本或图片），"
    "判断文档类型，并设计一套用于批量结构化提取的字段方案。只输出一个 JSON 对象，"
    "不要 markdown、不要解释。\n\n"
    "输出格式：\n"
    "{\n"
    '  "doc_type": "文档类型名（如 增值税发票/报关缴款书/送货单/合同/其他）",\n'
    '  "fields": [\n'
    '    {"key": "英文snake_case", "label": "中文名", '
    '"type": "text|number|date|checkbox|table|multiline",\n'
    '     "description": "提取提示（含位置/格式；table类型必须写成「列：key1 中文名1, '
    'key2 中文名2, …」）",\n'
    '     "group_key": false, "carry": "first", "sum_check": null}\n'
    "  ]\n"
    "}\n\n"
    "设计规则：\n"
    "1. 推荐 5-10 个关键字段；table 类型 0-2 个；key 全文档唯一。\n"
    "2. 表格字段的 description 必须用「列：key 中文名, …」列出所有列，"
    "key 用英文 snake_case——这是跨页合并的键名基准，必须给全。\n"
    "3. 若单据可能一份多页（明细跨页续行），给最稳定的单据编号字段设 "
    '"group_key": true；合计类字段设 "carry": "last"。\n'
    "4. 若存在「合计 = 明细某列之和」的关系，在合计字段上声明 "
    '"sum_check": {"table": "表格key", "column": "列key"}，系统会做本地算术校验。\n'
    "5. 金额类用 number；日期类用 date；勾选类用 checkbox。\n"
    "6. 严格基于证据设计，不要臆造证据中不存在的信息板块。")


def analyze_user(is_native, evidence, pages_note):
    head = ("以下是文档%s（%s）。请分析并输出字段方案 JSON：\n\n"
            % ("首部页面的版式文本" if is_native else "首页扫描图片", pages_note))
    if is_native:
        return head + evidence
    return head + (("【OCR辅助文本(可能有错，以图片为准)】\n" + evidence) if evidence else
                   "（请直接根据图片判断。）")


# ══════════════════════════════════════════════════════════════
#  AI-2 字段描述补全（前端小工具）
# ══════════════════════════════════════════════════════════════
COMPLETE_SYSTEM = ("你是文档提取助手。用户会给出一个待提取字段，"
                   "请用一句话（20字以内）描述该字段在此类文档中的典型位置与格式，"
                   "直接输出这句话本身，不要引号、不要解释。")


def complete_user(label, ftype, doc_ctx):
    return ("文档背景：%s\n字段：%s（类型 %s）\n"
            "示例风格：右上角No.后的编号 / 合计栏小写金额" % (doc_ctx or '未知', label, ftype))
