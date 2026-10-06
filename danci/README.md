# 不止单词 · 小红书小工具

背单词 + 抽卡收集。高考核心 688 词，35 组，每组 20 词。

## 交付物

`不止单词.zip`：上传到创服平台即可（`index.html` 在 zip 根目录）。

## 功能

- **练习**：英选中、中选英、看义拼写（例句挖空）、听音拼写、闪卡、错词本。每个词都有真人发音、例句、中文翻译，引用的诗文名言会标出处。
- **全部测试**：从 688 词里随机抽 25 题。每答对 1 题得 1 张抽卡券。
- **正确率加成**：只加在 SSR 及以上：
  - 60% 以上 ×1.2
  - 80% 以上 ×1.5
  - 90% 以上 ×2，另奖 3 张
  - 全对 ×3，另奖 5 张
- **分组练习**：每答对 2 题得 1 张券，基础概率。闪卡模式不发券。
- **抽卡**：7 个等级，18 款卡面。基础概率：
  - SECRET 0.2%
  - LR 0.8%
  - UR 3%
  - SSR 8%
  - SR 18%
  - R 30%
  - N 40%
- **保底**：十连必出 SR 以上，60 抽必出 SSR 以上，150 抽必出 UR 以上。
- **单词来源**：抽到的单词来自练过的词和当前分组。
- **火漆**：每张卡另抽一枚火漆，与卡面等级独立。素封 50%、珍封 30%、金封 15%、秘封 5%。同一单词、同一卡面、同一火漆才算重复。
- **星尘**：重复的卡折算成星尘，20 星尘可换 1 张券。
- **卡册与图鉴**：卡册每组一页；图鉴展示 18 款卡面；卡片详情可以拖动看镭射效果。
- **晒图**：卡片海报和成绩卡都用 Canvas 2D 生成，通过 `saveImageToPhotosAlbum` 存相册、`postNote` 发笔记。
- **存档**：客户端 9.46 及以上用容器 Storage，低版本退回浏览器存储。会自动迁移旧版（手账贴纸版）的学习记录。

## 构建

```bash
cd tools && npm install && cd ..   # 字体源、语法检查依赖（只需一次）
python3 tools/build.py             # 生成 dist/ 和 不止单词.zip，并自动审计
node tools/e2e.js                  # 可选：模拟容器把主要流程点一遍，截图在 tools/.shots/
```

依赖：Python 3（`pip install fonttools brotli pillow`）、Node 18+、Playwright 自带的 Chromium（仅预渲染和测试用）。

## 线稿与火漆素材

- 线稿：LR「极光情书」、SECRET「午夜星河」「月光恋人」三款使用。源图 `lineart-src/sheet.jpg`，处理参数在 `tools/build.py` 的 `FRAMING`。重新处理：`python3 tools/build.py --lineart lineart-src/sheet.jpg`
- 火漆：源图 `seals-src/*.jpg`，`python3 tools/seals.py` 抠图输出到 `src/img/seal/`。

## 兑换码（给粉丝发抽卡券）

入口藏在首页卡片右上角的火漆上：**长按**，或**连点三下**，会打开一封信，输入兑换码后拆开就到账。

- **防伪**：码是 12 位随机字符（60 位熵），一次生成好；小工具里只放每个码的指纹（加盐 SHA-256 迭代 4096 次，`src/js/gift-db.js`），不含任何能造码的密钥。看得到代码也推不出码。
- **全年周码**：已生成 2026-10-05 起 52 周，每周一批 30 个码、每个 10 张；周一生效，下周三截止。同一批每台手机限领一次，所以一个码可以直接发到粉丝群。
- 码在 `gift-codes/`（不进仓库，务必另存）。批次记录在 `tools/gift_batches.json`。

```bash
python3 tools/gift_codes.py --list                                            # 查看批次
python3 tools/gift_codes.py --extra --tickets 5 --days 3 --count 50 --note 直播  # 追加临时码（需重新打包上传）
python3 tools/gift_codes.py --year --force                                     # 整年重来（已发的码全部作废）
```

- 防不住的：码被转发、手机改日期、越狱后直接改本地存档。前两种影响很小（每台手机每批只能领一次）。

## 宣传片

`promo/不止单词-宣传片.mp4`：20 秒竖版（1080×1920，30fps）。画面直接用 app 的镭射卡、火漆和字体逐帧渲染；配乐和音效全部合成，音效与小工具共用 `tools/sfx.py`，发音用 app 里的真人录音。隐藏款只露出光缝里的一窄条。

```bash
python3 tools/build.py                                   # 先生成 dist/
node promo/capture.js /tmp/frames 60 0 20 4 3            # 逐帧截图（60fps、3 倍像素）
python3 promo/music.py /tmp/music.wav                    # 配乐
ffmpeg -framerate 30 -i /tmp/frames/%04d.jpg -i /tmp/music.wav -c:v libx264 -crf 17 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -af loudnorm=I=-14:TP=-1.5 -movflags +faststart -shortest promo/不止单词-宣传片.mp4
```

## 声音

- 发音：688 词真人录音（`audio-clips.js`）。音效：`tools/sfx.py` 合成，生成 `sfx-clips.js`。
- 播放优先走 Web Audio，起不来时退回 `<audio>`；iOS 每次手势都会重试解锁，并设置 `audioSession = playback`，静音键打开时也能出声（iOS 17+）。
- `node tools/audio_test.js`：在普通、模拟 iOS、无 Web Audio 三种环境下检查每一步都真正出声。

## 目录

- `src/`：源码
  - `index.html`：页面骨架
  - `css/`：样式
  - `js/`：`app.js` 主逻辑、`cards.js` 卡片渲染、`catalog.js` 卡面目录、`data.js` 词表与例句
  - `img/`：图片素材
- `tools/`：构建脚本
  - `build.py`：构建与审计
  - `prerender.js`：构建期把渐变背景渲染成图片
  - `sentences/`：例句源文件，格式 `序号|词性|释义|例句|译文|出处`
  - `build_data.js`：合并词表和例句
  - `vendor/`：cards-css（MIT），打包成 `src/js/holokit.js`
- `fonts-src/`：Instrument Serif（OFL）。Noto Serif SC（OFL）由 npm 安装后按用到的字裁成子集。

## 兼容与验证

- JS 全部按 ES2017 校验，CSS 按 Chrome 61 基线编写。不使用 Worker、陀螺仪、网络请求、内联脚本。
- 已在桌面 Chromium 里模拟容器完成自动化测试。
- **未在 Android 8.1 / Chrome 61 真机上实测。**
- 上传后请依次验证：创服平台模拟器 → Android 真机扫码 → iOS 真机扫码。
