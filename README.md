# 票据提取与 Excel 导出

这是一个本地运行的票据整理工具。上传 PDF 后，程序会识别票据内容、按配置提取字段、合并跨页记录，并把结果导出为 Excel。

项目适合处理电子 PDF、扫描件以及混合多页文件。文字识别和字段提取需要连接支持 Anthropic Messages 协议的模型服务。

## 主要功能

- 批量上传和处理 PDF
- 根据票据内容推荐提取字段
- 支持电子件和扫描件
- 合并同一单据的跨页内容
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

1. 上传一个或多个 PDF。
2. 选择预设方案，或让模型分析票据并生成字段方案。
3. 检查字段名称、类型及合并规则。
4. 开始提取，等待页面显示处理结果。
5. 检查校验提示并下载 Excel。

## 项目结构

```text
.
├── app.py              # Flask 服务和任务调度
├── ai_client.py        # 模型网关客户端
├── extractor.py        # 单页字段提取
├── pdf_utils.py        # PDF 文本读取、页面判断和渲染
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
| `MAX_TOKENS_CAP` | `16384` | 常规输出上限 |
| `HARD_TOKENS_CAP` | `32768` | 截断重试时的输出上限 |
| `REPAIR_MAX` | `6` | 单次任务最多复核记录数 |
| `AI_TIMEOUT` | `300` | 单次请求超时秒数 |

## 测试

安装测试依赖并运行离线测试：

```bash
python3 -m pip install -r requirements-dev.txt
python3 selftest.py
```

离线测试不需要模型服务。它会生成样例 PDF，并检查提取、跨页合并、校验、复核和 Excel 导出流程。

需要检查真实网关时，可以运行：

```bash
python3 selftest.py --live
python3 selftest.py --live --vision
```

仓库中的 GitHub Actions 会在推送和 Pull Request 时运行离线测试。

## 常见问题

- 文本测试成功、图片测试失败：当前模型可能不支持图片。扫描件可安装 `rapidocr-onnxruntime` 后使用 OCR。
- 网关返回与 `assistant` 相关的 400 错误：部分兼容网关不支持预填消息，程序会自动改用普通请求。
- 提取速度较慢：耗时通常取决于模型响应速度、PDF 页数和并发设置。

## 安全说明

- 不要把 Token 写进代码或提交到 Git。
- `.env`、上传文件和导出结果已加入 `.gitignore`。
- 当前版本默认用于本地环境。部署到公网前，需要补充登录认证、HTTPS、访问限流和持久化存储。
