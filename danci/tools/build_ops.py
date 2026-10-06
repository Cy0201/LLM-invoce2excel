#!/usr/bin/env python3
"""打包运营工具：python3 tools/build_ops.py（先运行 build.py）
以 dist/ 为底，加上全年兑换码和运营页，输出 gift-codes/不止单词运营.zip。
里面有全部兑换码：只自己扫码预览用，绝不上架、不外传；输出目录 gift-codes/ 不进仓库。"""
import csv, glob, json, os, shutil, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST, OUT = os.path.join(ROOT, 'dist'), os.path.join(ROOT, 'gift-codes', 'ops')
csv_path = glob.glob(os.path.join(ROOT, 'gift-codes', '全年周码_*.csv'))[0]
weeks = {}
for r in csv.DictReader(open(csv_path, encoding='utf-8-sig')):
    w = weeks.setdefault(r['批次'], {'week': int(r['批次'][1:]), 'from': r['生效日'], 'to': r['截止日（含）'], 'tickets': int(r['每个码张数']), 'codes': []})
    w['codes'].append(r['兑换码'])
shutil.rmtree(OUT, ignore_errors=True)
shutil.copytree(DIST, OUT)
open(os.path.join(OUT, 'js', 'ops-codes.js'), 'w', encoding='utf-8').write('window.OPS_CODES=' + json.dumps(sorted(weeks.values(), key=lambda x: x['week']), ensure_ascii=False) + ';\n')
for f in ('ops.js', 'ops.css'):
    shutil.copy(os.path.join(ROOT, 'tools', 'ops', f), os.path.join(OUT, 'js' if f.endswith('.js') else 'css', f))
idx = os.path.join(OUT, 'index.html')
html = open(idx, encoding='utf-8').read()
html = html.replace('<title>不止单词</title>', '<title>不止单词 · 运营</title>')
html = html.replace('</head>', '<link rel="stylesheet" href="./css/ops.css" />\n</head>')
html = html.replace('<script src="./js/app.js"></script>', '<script src="./js/app.js"></script>\n<script src="./js/ops-codes.js"></script>\n<script src="./js/ops.js"></script>')
open(idx, 'w', encoding='utf-8').write(html)
zp = os.path.join(ROOT, 'gift-codes', '不止单词运营.zip')
with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(OUT):
        for n in files:
            p = os.path.join(root, n)
            z.write(p, os.path.relpath(p, OUT))
print('运营包：%s（%.2f MiB，%d 周）' % (os.path.relpath(zp, ROOT), os.path.getsize(zp) / 1048576, len(weeks)))
