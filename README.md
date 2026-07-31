# 票据智能提取台 v7

> AI 驱动的轻量化通用票据管理平台 — 上传票据 PDF，AI 自动识别、提取字段、跨页合并、算术校验，一键导出三表 Excel。

上传任意 PDF 票据（电子件 / 扫描件 / 混合多页、一份文件里混多张单据都行），
AI 识别文档类型并推荐字段方案 → 可视化编辑 → 批量提取 → 跨页合并 →
本地算术校验 → 不一致自动 AI 复核 → 导出三表 Excel。

AI 只依赖一个 **Anthropic Messages 协议**接口。**首次使用前需要在浏览器右上角"网关设置"中填写网关地址、Token 和模型名**，也可以在启动前设置环境变量。

## 功能特性

- 自动识别票据类型并推荐字段提取方案
- 支持电子件、扫描件、混合多页票据
- AI 智能提取 + 可视化编辑
- 跨页单据自动合并
- 本地算术校验 + 不一致自动 AI 复核
- 一键导出三表 Excel（汇总 / 明细 / 校验）
- 兼容任意 Anthropic Messages 协议网关（内网 / 官方端点通用）

## 快速开始

```bash
pip install -r requirements.txt          # 建议同时装 rapidocr-onnxruntime
bash run.sh                              # 或 python3 app.py -p 5000
# 浏览器打开 http://localhost:5000 ，右上角"网关设置 → 测试连接"先自检
```

### 使用官方 Claude API

```bash
export ANTHROPIC_BASE_URL="https://api.anthropic.com"
export ANTHROPIC_AUTH_TOKEN="sk-ant-…"
export CLAUDE_MODEL="claude-sonnet-4-6"
bash run.sh
```

## 安装依赖

```bash
pip install -r requirements.txt
```

### 可选依赖

| 依赖 | 用途 |
|---|---|
| `rapidocr-onnxruntime` | 本地 OCR，扫描件质量大幅提升 |
| `json_repair` | 更强的坏 JSON 修复（内置修复已覆盖常见情况） |
| `reportlab` | 仅自测需要，生成中文样例 PDF |

## 项目结构

```
.
├── app.py              # Flask 服务：任务编排 / SSE / 复核回路 / 下载
├── pdf_utils.py        # 三态页判定、版式文本、精确渲染、OCR 版式重建
├── ai_client.py        # 网关客户端：预填 / 思考抑制 / 双头认证 / JSON 容错解析
├── extractor.py        # 单页提取引擎：提示词契约 + 失败阶梯
├── merge.py            # 列声明解析、续页感知合并、carry、本地求和校验
├── excel_export.py     # 汇总 / 明细 / 校验 三表导出
├── presets.py          # 预设字段库 + 分析 / 补全提示词
├── claude_sim.py       # 离线测试用 AI 仿真器（按真实契约工作，支持故障注入）
├── selftest.py         # 离线全链路自测 + 内网真实网关冒烟 (--live)
├── templates/
│   └── index.html      # 前端（预设 / 字段编辑 / 测试连接 / 进度 / 结果 / 校验面板）
├── requirements.txt    # Python 依赖
├── run.sh              # Linux/macOS 启动脚本
├── run.bat             # Windows 启动脚本
└── README.md
```

## 自测

```bash
python3 selftest.py            # 离线全链路（36 项，不需要网络 / 网关）
python3 selftest.py --live     # 内网机器上：真实网关连通 + 单页真实提取冒烟
python3 selftest.py --live --vision   # 追加视觉链路探测
```

### 离线测试说明

离线模式用 reportlab 现场生成真实中文 PDF（3 页缴款书含跨页单据、图片型送货单、
空白页），以一个**按真实提示词契约工作的 AI 仿真器**（`claude_sim.py`）跑通
Flask → SSE → 合并 → 校验 → 复核 → Excel 全链路，并注入四类故障验证提取阶梯：

- 坏 JSON → 提醒重试
- 输出截断 → 升额重试
- 数值错误 → 自动复核修正
- 网关无视觉 → 自动降级 OCR

## 字段方案怎么写

- **合并键**（group_key）：同一单据跨页时值相同的字段，如报关单编号。
- **取值**（carry）：跨页合并时标量取 first/last；印在末页的"合计"用 last。
- **求和校验**（sum_check）：填 `表key.列key`，系统本地核对 本字段 = 该列求和，
  不一致自动复核。
- **表格列**：在提取说明里写 `列：seq 序号, name 品名, …`（key 用英文 snake_case）。这是跨页合并与求和校验的键名基准。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `ANTHROPIC_BASE_URL` | (空) | 网关地址，**必须在前端或环境变量中填写** |
| `ANTHROPIC_AUTH_TOKEN` | (空) | Token，**必须在前端或环境变量中填写** |
| `CLAUDE_MODEL` | (空) | 模型名，**必须在前端或环境变量中填写** |
| `SCAN_MAX_SIDE` / `REPAIR_IMG_SIDE` | 2000 / 2400 | 常规 / 复核渲染长边像素 |
| `TEXT_WORKERS` / `VISION_WORKERS` | 8 / 3 | 两类请求并发 |
| `MAX_TOKENS_CAP` / `HARD_TOKENS_CAP` | 16384 / 32768 | 常规 / 升额输出上限 |
| `REPAIR_MAX` | 6 | 每任务最多自动复核的记录数 |
| `AI_TIMEOUT` | 300 | 单请求超时（秒） |

## v7 相比 v6 重点改进

### 质量

| 问题（旧版） | v7 做法 |
|---|---|
| `extract_text()` 丢失列对齐，表格在模型眼里成一锅粥 | `layout=True` 版式文本 + 无损压缩，整页完整喂给模型，**彻底移除截断** |
| 扫描判定只看"有没有字"，劣质文本层被当电子件 | 三态判定：整页图占比>0.7 → 按扫描件走视觉；乱码占比检测；空白页直接跳过 |
| 渲染质量不一致，小字号金额糊掉 | 按目标长边**精确反推缩放一次渲染**（默认 2000px/q88，复核 2400px/q92） |
| 标量与表格分两次请求，合计和明细对不上 | **单页一次请求**同时出标量+表格，合计与明细同源 |
| `max_tokens` 截断被静默吞掉 | 检测 `stop_reason=max_tokens` → 自动升额到 32768 重试 |
| 合计校验只报错，不修 | 不一致自动触发复核：更高清重渲 + 差额提示，修好标记"⟳已复核" |
| 续页没印单据编号时跨页合并断链 | 续页感知合并，编号缺失但 `_is_continuation=true` 即并入 |
| 模型偶尔用中文列名回行，并表/求和错位 | 声明式列约定 + 行键 label→key 自动重映射 |

### 稳健

- 中文文件名原样保留（旧版 `secure_filename` 把中文剥光 → 多文件互相覆盖）
- 结果按 `job_id` 隔离（旧版全局 `_last`，并发时互相串档）
- 预填 `{` 锁 JSON 输出；网关不接受 assistant 预填时自动降级
- qwen 系思考抑制双保险
- 网关无视觉能力：首次发现即全任务降级 OCR 文本路线
- 坏 PDF 不拖垮同批其他文件；单页失败只标红该记录

### 速度

- 所有文件的所有页摊平进两个线程池并发（文本 8 / 视觉 3）
- 每页请求数从 ≥2 降到 1（拆分只在兜底时发生）
- 空白页零请求跳过；`max_tokens` 动态估算

## 排障

- **测试连接：文本 ✓ 视觉 ✗** → 网关 / 模型不支持图片。安装 `rapidocr-onnxruntime`。
- **报"只输出了思考块"** → 网关未透传思考开关，请关闭思考或换非思考模型。
- **响应 400 提到 assistant** → 该网关不接受预填，程序已自动降级，无需处理。
- **提取很慢** → 确认是不是模型生成慢（`--live` 冒烟会打印单页耗时）。