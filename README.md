# AI驱动的轻量化通用票据识别提取转化工具

这是一个本地运行的票据整理工具。上传 PDF 或图片后，程序会识别内容、按配置提取字段、合并跨页记录，并把结果导出为 Excel。

项目支持电子 PDF、扫描件、JPG、PNG、WebP、BMP、TIFF 和 GIF。文字识别和字段提取需要连接支持 Anthropic Messages 协议的模型服务。

## 主要功能

- 批量混合上传 PDF 和图片
- 根据票据内容推荐提取字段
- 支持电子件和扫描件
- 合并同一单据的跨页内容
- 拆分同一 PDF 内交错出现的不同逻辑文档
- 统一不同版式中的标量字段和重复行明细
- 核对合计值与明细金额
- 导出汇总、明细、校验三个 Excel 工作表
- 支持自定义 Anthropic 兼容网关

## 运行环境

- Python 3.9 或更高版本
- 可访问的 Anthropic 兼容模型服务
- 处理扫描件时建议安装 `rapidocr-onnxruntime`

## 快速开始

### Windows

双击 `run.bat`。脚本会创建虚拟环境、安装依赖并启动服务。

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
bash run.sh
```

启动后访问 <http://localhost:5000>，在页面右上角填写网关地址、Token 和模型名，然后先测试连接。

也可以通过环境变量提供配置：

```bash
export ANTHROPIC_BASE_URL="https://api.anthropic.com"
export ANTHROPIC_AUTH_TOKEN="你的 Token"
export CLAUDE_MODEL="你的模型名"
bash run.sh
```

## 使用流程

1. 上传一个或多个 PDF 或图片。
2. 选择预设方案，或让模型分析票据并生成字段方案。
3. 检查字段名称、类型及合并规则。
4. 开始提取，等待页面显示处理结果。
5. 检查校验提示并下载 Excel。

## 三种提取模式

页面上的三个选项分别对应三种不同需求：

- **固定格式精准提取**：原有流程不变，适合同一种版式的批量 PDF 或图片。可以使用预设字段、跨页合并、合计校验和自动复核。
- **同类票据跨版式提取**：适合不同银行的对账单、不同模板的同类发票等。AI 会根据业务含义判断字段和交易明细列，允许字段名称、语言、位置和表格结构不同，再统一输出同一类票据的数据。
- **混合异构文档分别提取**：适合合同、发票、发货单等不同类型文档混在同一个 PDF 或多个文件中的情况。AI 先识别页面类型、复核逻辑文档边界，再为每种类型单独生成字段方案；合同的专有字段、发票的专有字段和各自明细都会保留，不会被压成只剩公共字段。

前两种 AI 模式都支持先分析字段方案、人工修改后再提取；也可以直接点击一键按钮自动完成分析和提取。混合模式的一键流程会自动完成“识别类型 → 拆分逻辑文档 → 按类型建模 → 分类型提取”。

AI 不依赖项目内置的银行名称、票据版式或固定坐标规则。字段名称不一致时，会依据字段说明、页面上下文、表头和数值关系判断业务含义；无法可靠判断的字段或文档边界会保留证据并标记待复核。

Excel 导出会根据模式生成对应的汇总、明细、字段证据和文档边界工作表。

## 项目结构

```text
.
├── app.py              # Flask 服务和任务调度
├── ai_client.py        # 模型网关客户端
├── extractor.py        # 单页字段提取
├── pdf_utils.py        # PDF/图片读取、页面判断和渲染
├── common_mode.py      # 异构字段建模、边界复核和统一归组
├── mixed_mode.py       # 混合异构文档按类型拆分、字段方案和结果组装
├── common_export.py    # 异构结果、证据、边界和明细导出
├── merge.py            # 跨页合并与数值校验
├── excel_export.py     # Excel 导出
├── presets.py          # 内置字段方案
├── claude_sim.py       # 离线测试使用的模型模拟器
├── selftest.py         # 离线自测和在线冒烟测试
├── templates/
│   └── index.html      # 前端页面
├── requirements.txt
├── requirements-dev.txt
├── run.bat
└── run.sh
```

## 字段配置

字段方案中有几个配置会影响跨页合并和校验：

- `group_key`：同一张单据各页共有的字段，例如报关单编号。
- `carry`：合并时保留第一页或最后一页的值，可选 `first` 或 `last`。
- `sum_check`：检查某个字段是否等于明细列合计，格式为 `表key.列key`。
- 表格列：列的 key 建议使用英文 `snake_case`，避免合并时出现名称不一致。

## 环境变量

| 变量 | 默认值 | 用途 |
|---|---:|---|
| `ANTHROPIC_BASE_URL` | 空 | 模型网关地址 |
| `ANTHROPIC_AUTH_TOKEN` | 空 | 模型服务 Token |
| `CLAUDE_MODEL` | 空 | 模型名称 |
| `SCAN_MAX_SIDE` | `2000` | 扫描页图片长边像素 |
| `REPAIR_IMG_SIDE` | `2400` | 复核图片长边像素 |
| `TEXT_WORKERS` | `8` | 文本任务并发数 |
| `VISION_WORKERS` | `3` | 图片任务并发数 |
| `MAX_TOKENS_CAP` | `1638400` | 同类票据常规输出上限 |
| `HARD_TOKENS_CAP` | `3276800` | 同类票据截断重试时的输出上限 |
| `COMMON_OBSERVE_TOKENS` | `8192` | 异构模式代表页观察输出上限 |
| `COMMON_BATCH_TOKENS` | `16384` | 异构模式分批字段归纳输出上限 |
| `COMMON_ANALYZE_TOKENS` | `32768` | 异构模式最终字段合并输出上限 |
| `COMMON_EXTRACT_TOKENS` | `65536` | 异构模式单页统一提取输出上限 |
| `COMMON_SAMPLE_PAGES` | `64` | 异构模式基础代表页预算；文件数更多时至少每个文件观察一页 |
| `COMMON_SEGMENT_TOKENS` | `32768` | 文档边界复核输出上限 |
| `COMMON_SEGMENT_PAGES` | `40` | 每次边界复核处理的页数 |
| `COMMON_SEGMENT_ACTIVE` | `80` | 分段复核时保留的活跃文档锚点数 |
| `REPAIR_MAX` | `6` | 单次任务最多复核记录数 |
| `AI_TIMEOUT` | `300` | 单次请求超时秒数 |

## 测试

安装测试依赖并运行离线测试：

```bash
python3 -m pip install -r requirements-dev.txt
python3 selftest.py
```

离线测试不需要模型服务。它会生成 PDF 和图片样本，并检查提取、跨页合并、异构边界复核、
统一明细、图片直传、三种提取模式、混合文档拆分、校验和 Excel 导出流程。

需要检查真实网关时，可以运行：

```bash
python3 selftest.py --live
python3 selftest.py --live --vision
```

仓库中的 GitHub Actions 会在推送和 Pull Request 时运行离线测试。

## 常见问题

- 文本测试成功、图片测试失败：当前模型可能不支持图片。扫描件可安装 `rapidocr-onnxruntime` 后使用 OCR。
- 网关返回与 `assistant` 相关的 400 错误：部分兼容网关不支持预填消息，程序会自动改用普通请求。
- 内网网关提示 10061 或超时：程序会自动绕过系统 HTTP 代理，直连 `10.*`、`172.16.*`、`192.168.*` 和本机地址；公网网关仍沿用系统代理。
- 提取速度较慢：耗时通常取决于模型响应速度、PDF 页数和并发设置。
