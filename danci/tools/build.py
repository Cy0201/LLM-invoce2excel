#!/usr/bin/env python3
"""单词手账 · 小红书小工具构建脚本

用法（在 danci/ 目录下）：
  python3 tools/build.py                          # 构建 dist/ 并打包 单词手账.zip
  python3 tools/build.py --lineart 线稿拼图.png    # 先把 UR 以上 6 张线稿切好放进卡面，再构建
  python3 tools/build.py --lineart 线稿.png --grid 3x2 --order ur1,ur2,lr1,lr2,x1,x2

依赖：Python 3 + fonttools + brotli + pillow；Node（tools/ 下 npm install，用于字体源和语法检查）
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src')
DIST = os.path.join(ROOT, 'dist')
TOOLS = os.path.join(ROOT, 'tools')
ZIP_NAME = '单词手账.zip'

# 线稿拼图默认 3 列 × 2 行，从左到右、从上到下依次对应以下 6 款卡面
DEFAULT_ORDER = ['ur1', 'ur2', 'lr1', 'lr2', 'x1', 'x2']
PORTRAIT = (600, 926)   # 竖版卡底图尺寸（250:386）
LANDSCAPE = (926, 600)  # 横版卡（Clair de Lune）


def log(*a):
    print('[build]', *a)


# ---------------------------------------------------------------- 线稿
def catalog_slots():
    """从 catalog.js 读出 slot 卡面的墨色与是否横版"""
    js = open(os.path.join(SRC, 'js', 'catalog.js'), encoding='utf-8').read()
    info = {}
    for m in re.finditer(r"\{ id: '(\w+)'[^\n]*?slot: (\d)[^\n]*?ink: '(#[0-9A-Fa-f]{6})'", js):
        vid, slot, ink = m.group(1), int(m.group(2)), m.group(3)
        line = js[m.start():js.index('\n', m.start())]
        info[vid] = {'slot': slot, 'ink': ink, 'land': 'land: 1' in line}
    return info


def process_lineart(sheet, grid, order):
    from PIL import Image, ImageOps
    cols, rows = [int(x) for x in grid.lower().split('x')]
    slots = catalog_slots()
    im = Image.open(sheet).convert('L')
    W, H = im.size
    cw, ch = W / cols, H / rows
    out_dir = os.path.join(SRC, 'lineart')
    os.makedirs(out_dir, exist_ok=True)
    mapping = {}
    for idx, vid in enumerate(order):
        if idx >= cols * rows:
            break
        c, r = idx % cols, idx // cols
        inset = 0.015
        box = (int(c * cw + cw * inset), int(r * ch + ch * inset), int((c + 1) * cw - cw * inset), int((r + 1) * ch - ch * inset))
        cell = im.crop(box)
        info = slots.get(vid, {'ink': '#3B3570', 'land': False})
        # 线条 → 透明度：越黑越不透明；纸色、浅灰噪点变透明
        gray = ImageOps.autocontrast(cell, cutoff=1)
        alpha = gray.point(lambda g: max(0, min(255, int((238 - g) * 255 / 170))))
        if info['land']:
            # 横版卡：人物放在右侧，左边留给单词和例句
            tw, th = LANDSCAPE
            scale = th / alpha.height
            a = alpha.resize((max(1, int(alpha.width * scale)), th), Image.LANCZOS)
            canvas = Image.new('L', (tw, th), 0)
            canvas.paste(a, (tw - a.width - int(tw * 0.02), 0))
            alpha = canvas
        else:
            tw, th = PORTRAIT
            scale = max(tw / alpha.width, th / alpha.height)
            a = alpha.resize((max(tw, int(alpha.width * scale + .5)), max(th, int(alpha.height * scale + .5))), Image.LANCZOS)
            left = (a.width - tw) // 2
            alpha = a.crop((left, 0, left + tw, th))  # 顶部对齐，保住头部
        rgb = Image.new('RGB', alpha.size, info['ink'])
        rgba = rgb.copy()
        rgba.putalpha(alpha)
        path = os.path.join(out_dir, vid + '.webp')
        rgba.save(path, 'WEBP', quality=86, method=6)
        mapping[vid] = 'lineart/' + vid + '.webp'
        log('线稿', vid, '→', os.path.relpath(path, ROOT), os.path.getsize(path), 'bytes')
    with open(os.path.join(SRC, 'js', 'lineart.js'), 'w', encoding='utf-8') as f:
        f.write('/* 人物线稿位（UR 及以上 6 款）。由 tools/build.py --lineart <拼图> 生成；为空时卡面不显示线稿。 */\n')
        f.write('window.LINEART = ' + json.dumps(mapping, ensure_ascii=False) + ';\n')


# ---------------------------------------------------------------- 字体
CJK = re.compile(r'[ -⁯　-〿㐀-鿿＀-￯]')


def cjk_chars(text):
    return set(CJK.findall(text))


def load_words():
    js = open(os.path.join(SRC, 'js', 'data.js'), encoding='utf-8').read()
    return json.loads(js[js.index('=') + 1:js.rindex(';')])


def subset_noto(weight, chars, out_path):
    from fontTools import subset
    from fontTools.merge import Merger
    from fontTools.ttLib import TTFont
    files_dir = os.path.join(TOOLS, 'node_modules', '@fontsource', 'noto-serif-sc', 'files')
    if not os.path.isdir(files_dir):
        log('安装字体源（npm install）…')
        subprocess.check_call(['npm', 'install', '--silent'], cwd=TOOLS)
    need = {ord(c) for c in chars}
    parts = []
    tmp = tempfile.mkdtemp()
    for name in sorted(os.listdir(files_dir)):
        if not name.endswith('-%d-normal.woff2' % weight):
            continue
        path = os.path.join(files_dir, name)
        f = TTFont(path)
        have = need & set(f.getBestCmap().keys())
        if not have:
            continue
        opts = subset.Options()
        opts.flavor = None
        opts.layout_features = ['*']
        opts.name_IDs = ['*']
        opts.notdef_outline = True
        opts.hinting = False
        s = subset.Subsetter(opts)
        s.populate(unicodes=have)
        s.subset(f)
        p = os.path.join(tmp, name.replace('.woff2', '.ttf'))
        f.flavor = None
        f.save(p)
        parts.append(p)
    if not parts:
        raise SystemExit('字体子集为空')
    merged = Merger().merge(parts)
    merged.flavor = 'woff2'
    merged.save(out_path)
    shutil.rmtree(tmp)
    got = set(TTFont(out_path).getBestCmap().keys())
    miss = [chr(c) for c in need - got if c > 127]
    log('字体 Noto Serif SC %d：%d 字，%d KB' % (weight, len(got), os.path.getsize(out_path) // 1024) + ('，源字体缺字：' + ''.join(miss[:20]) if miss else ''))


def build_fonts():
    fonts = os.path.join(DIST, 'fonts')
    os.makedirs(fonts, exist_ok=True)
    ui = set()
    for rel in ['index.html', 'js/app.js', 'js/catalog.js', 'js/cards.js']:
        ui |= cjk_chars(open(os.path.join(SRC, rel), encoding='utf-8').read())
    words = load_words()
    cm, cn, src = set(), set(), set()
    for r in words:
        cm |= cjk_chars(r[7] + r[8])
        cn |= cjk_chars(r[10])
        src |= cjk_chars(r[11])
    ascii_ = {chr(c) for c in range(32, 127)}
    punct = set('，。；：“”‘’！？、—…·（）《》「」·×％')
    subset_noto(600, ui | cm | src | ascii_ | punct, os.path.join(fonts, 'noto-serif-sc-600.woff2'))
    subset_noto(300, ui | cn | src | cm | ascii_ | punct, os.path.join(fonts, 'noto-serif-sc-300.woff2'))
    for n in ['instrument-serif-latin-400-normal.woff2', 'instrument-serif-latin-400-italic.woff2']:
        shutil.copy(os.path.join(ROOT, 'fonts-src', n), os.path.join(fonts, n))
    css = '''/* 包内字体（子集）：容器不联网。Instrument Serif、Noto Serif SC 均为 OFL-1.1 */
@font-face{font-family:"Instrument Serif";font-style:normal;font-weight:400;font-display:swap;src:url("../fonts/instrument-serif-latin-400-normal.woff2") format("woff2")}
@font-face{font-family:"Instrument Serif";font-style:italic;font-weight:400;font-display:swap;src:url("../fonts/instrument-serif-latin-400-italic.woff2") format("woff2")}
@font-face{font-family:"Noto Serif SC";font-style:normal;font-weight:300;font-display:swap;src:url("../fonts/noto-serif-sc-300.woff2") format("woff2")}
@font-face{font-family:"Noto Serif SC";font-style:normal;font-weight:600;font-display:swap;src:url("../fonts/noto-serif-sc-600.woff2") format("woff2")}
'''
    with open(os.path.join(DIST, 'css', 'fonts.css'), 'w', encoding='utf-8') as f:
        f.write(css)


# ---------------------------------------------------------------- 组装
def assemble():
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    shutil.copytree(SRC, DIST, ignore=shutil.ignore_patterns('.DS_Store', '*.map'))
    # 未生成线稿时去掉空目录
    la = os.path.join(DIST, 'lineart')
    if os.path.isdir(la) and not os.listdir(la):
        os.rmdir(la)
    # 图标雪碧图内联进 index.html
    idx = os.path.join(DIST, 'index.html')
    html = open(idx, encoding='utf-8').read()
    icons = open(os.path.join(TOOLS, 'icons.svg'), encoding='utf-8').read()
    html = html.replace('<!--ICONS-->', '<defs>' + icons + '</defs>' if False else icons)
    open(idx, 'w', encoding='utf-8').write(html)
    build_fonts()


def referenced_ok():
    """检查 HTML/CSS/JS 里引用的本地资源都在 dist 中"""
    bad = []
    for root, _, files in os.walk(DIST):
        for n in files:
            if not n.endswith(('.html', '.css', '.js')) or n == 'audio-clips.js':
                continue
            p = os.path.join(root, n)
            text = open(p, encoding='utf-8').read()
            for m in re.finditer(r'''(?:src=["']|url\(["']?|href=["'])(\.{0,2}/?[\w./-]+\.(?:webp|png|jpg|svg|woff2|css|js))''', text):
                ref = m.group(1)
                base = root if ref.startswith('.') else DIST
                q = os.path.normpath(os.path.join(base, ref))
                if not os.path.exists(q):
                    bad.append((os.path.relpath(p, DIST), ref))
            for m in re.finditer(r"'(img/(?:art|bg|charm|icon3d)/)' \+", text):
                pass
    # 运行时拼出来的路径
    for vid in re.findall(r"id: '(\w+)'", open(os.path.join(DIST, 'js', 'catalog.js'), encoding='utf-8').read()):
        if not os.path.exists(os.path.join(DIST, 'img', 'art', vid + '.webp')):
            bad.append(('catalog', 'img/art/' + vid + '.webp'))
    for k in ['home', 'quiz', 'result', 'album', 'reveal', 'gallery', 'test', 'sky', 'dusk', 'night']:
        if not os.path.exists(os.path.join(DIST, 'img', 'bg', k + '.webp')):
            bad.append(('bg', k))
    return bad


def make_zip():
    out = os.path.join(ROOT, ZIP_NAME)
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, dirs, files in os.walk(DIST):
            dirs.sort()
            for n in sorted(files):
                if n.startswith('.'):
                    continue
                p = os.path.join(root, n)
                arc = os.path.relpath(p, DIST).replace(os.sep, '/')
                zi = zipfile.ZipInfo(arc, date_time=(2026, 10, 5, 0, 0, 0))
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = 0o644 << 16
                with open(p, 'rb') as f:
                    z.writestr(zi, f.read(), compresslevel=9)
    return out


def checks(zip_path):
    ok = True
    bad = referenced_ok()
    if bad:
        ok = False
        for b in bad:
            log('缺少资源', b)
    # 容器禁用能力扫描
    banned = [r'\bfetch\(', r'XMLHttpRequest', r'new WebSocket', r'new EventSource', r'new Worker', r'SharedWorker', r'\beval\(',
              r'new Function\(', r'WebAssembly\.', r'window\.open\(', r'window\.prompt\(', r'navigator\.clipboard', r'deviceorientation',
              r'DeviceOrientationEvent', r'DeviceMotionEvent', r'requestFullscreen', r'serviceWorker', r'geolocation', r'target="_blank"',
              r'<iframe', r'type="module"', r'https?://(?!www\.w3\.org)']
    for root, _, files in os.walk(DIST):
        for n in files:
            if not n.endswith(('.html', '.js', '.css')) or n == 'audio-clips.js':
                continue
            p = os.path.join(root, n)
            text = open(p, encoding='utf-8').read()
            for pat in banned:
                for m in re.finditer(pat, text):
                    ok = False
                    log('禁用能力', os.path.relpath(p, DIST), pat, text[max(0, m.start() - 40):m.end() + 40].replace('\n', ' '))
            if n.endswith('.html') and re.search(r'<script(?![^>]*\bsrc=)[^>]*>', text):
                ok = False
                log('内联脚本', n)
            if n.endswith('.html') and re.search(r'\son[a-z]+=', text):
                ok = False
                log('行内事件', n)
    # ES2017 语法检查
    try:
        subprocess.check_call(['node', os.path.join(TOOLS, 'check_es2017.js')] + [os.path.join(DIST, 'js', n) for n in sorted(os.listdir(os.path.join(DIST, 'js')))])
    except subprocess.CalledProcessError:
        ok = False
    # 官方审计脚本
    for target in [DIST, zip_path]:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'audit_artifact.py'), target], capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode:
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description='构建单词手账小工具 zip')
    ap.add_argument('--lineart', help='6 张线稿拼成的一张图（默认 3 列 × 2 行）')
    ap.add_argument('--grid', default='3x2', help='拼图的列 x 行，默认 3x2')
    ap.add_argument('--order', default=','.join(DEFAULT_ORDER), help='格子对应的卡面，默认 ' + ','.join(DEFAULT_ORDER))
    a = ap.parse_args()
    if a.lineart:
        process_lineart(a.lineart, a.grid, a.order.split(','))
    assemble()
    z = make_zip()
    log('打包完成', os.path.relpath(z, ROOT), '%.2f MiB' % (os.path.getsize(z) / 1048576))
    if not checks(z):
        raise SystemExit('检查未通过')
    log('全部检查通过')


if __name__ == '__main__':
    main()
