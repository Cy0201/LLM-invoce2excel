#!/usr/bin/env python3
"""生成兑换码（离线校验，算法与 src/js/gift.js 一致）。

用法：
  python3 tools/gift_codes.py                        # 默认：每个码 10 张，7 天有效，生成 30 个
  python3 tools/gift_codes.py --tickets 5 --days 3 --count 100
  python3 tools/gift_codes.py --list                 # 查看发过的批次

规则：
- 同一批次里的码，每台手机只能兑换一次（领过这一批就不能再领这一批的其他码）。
  所以一个码可以直接发给一群人；想让同一个人再领，就发新批次。
- 有效期含最后一天；过期自动失效，不需要重新上传小工具。
- 码会写到 gift-codes/（已加入 .gitignore，不进仓库）；批次记录写到 tools/gift_batches.json。
"""
import argparse
import datetime
import json
import os
import random
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIFT_JS = os.path.join(ROOT, 'src', 'js', 'gift.js')
LOG = os.path.join(ROOT, 'tools', 'gift_batches.json')
OUT = os.path.join(ROOT, 'gift-codes')
AB = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
EPOCH = datetime.date(2026, 1, 1)
M32 = 0xFFFFFFFF


def imul(a, b):
    return (a * b) & M32


def h32(s, seed):
    h1, h2 = (0xdeadbeef ^ seed) & M32, (0x41c6ce57 ^ seed) & M32
    for ch in s:
        c = ord(ch)
        h1 = imul(h1 ^ c, 2654435761)
        h2 = imul(h2 ^ c, 1597334677)
    h1 = imul(h1 ^ (h1 >> 16), 2246822507) ^ imul(h2 ^ (h2 >> 13), 3266489909)
    h2 = imul(h2 ^ (h2 >> 16), 2246822507) ^ imul(h1 ^ (h1 >> 13), 3266489909)
    return (h1 ^ h2) & M32


def secret():
    return re.search(r"var K = '([^']+)'", open(GIFT_JS, encoding='utf-8').read()).group(1)


def make(k, batch, n, day, serial):
    lo = (batch << 22) | (day << 10) | serial
    sig = h32('%s|%d|%d' % (k, lo, n), 7) & 0xFFFFFF
    hi = sig * 64 + n
    lo2 = lo ^ (h32('%s#%d' % (k, sig), 11) & 0x3FFFFFFF)
    s = ''
    for word in (hi, lo2):
        s += ''.join(AB[(word >> (5 * (5 - i))) & 31] for i in range(6))
    return s[:4] + '-' + s[4:8] + '-' + s[8:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tickets', type=int, default=10, help='每个码给几张抽卡券（1–63）')
    ap.add_argument('--days', type=int, default=7, help='有效天数，从今天算起（含今天）')
    ap.add_argument('--count', type=int, default=30, help='生成几个码（每批最多 1024）')
    ap.add_argument('--batch', type=int, help='指定批次号（0–255），默认自动递增')
    ap.add_argument('--note', default='', help='备注，比如「粉丝群 10 月」')
    ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    log = json.load(open(LOG, encoding='utf-8')) if os.path.exists(LOG) else []
    if a.list:
        for b in log:
            print('批次 %(batch)3d  %(tickets)2d 张  截止 %(expires)s  %(count)4d 个  %(created)s  %(note)s' % b)
        return
    assert 1 <= a.tickets <= 63, '张数 1–63'
    assert 1 <= a.count <= 1024, '每批最多 1024 个'
    batch = a.batch if a.batch is not None else (max([b['batch'] for b in log]) + 1 if log else 1)
    assert 0 <= batch <= 255, '批次号 0–255'
    today = datetime.date.today()
    last = today + datetime.timedelta(days=a.days - 1)
    day = (last - EPOCH).days
    k = secret()
    serials = random.SystemRandom().sample(range(1024), a.count)
    codes = [make(k, batch, a.tickets, day, s) for s in serials]
    # 用 app 里的 JS 校验一遍，确保两边算法一致
    js = open(GIFT_JS, encoding='utf-8').read()
    check = subprocess.run(['node', '-e', 'global.window={};' + js + ';const c=JSON.parse(process.argv[1]);'
                            'const r=c.map(x=>window.GiftCode.parse(x));'
                            'console.log(JSON.stringify(r.every(x=>x.ok)&&r.map(x=>x.batch+","+x.n).filter((v,i,a)=>a.indexOf(v)===i)))',
                            json.dumps(codes)], capture_output=True, text=True)
    ok = check.stdout.strip()
    assert ok == json.dumps(['%d,%d' % (batch, a.tickets)]).replace(' ', ''), '校验失败：' + check.stdout + check.stderr
    os.makedirs(OUT, exist_ok=True)
    name = os.path.join(OUT, '批次%03d_%d张_至%s.txt' % (batch, a.tickets, last.strftime('%m%d')))
    with open(name, 'w', encoding='utf-8') as f:
        f.write('单词手账 兑换码 · 批次 %d · 每个 %d 张抽卡券 · 有效期至 %s（含当天）\n' % (batch, a.tickets, last.isoformat()))
        f.write('兑换方式：长按首页卡片上的蜡封（或连点三下），输入兑换码。同一批每台手机限领一次。\n\n')
        f.write('\n'.join(codes) + '\n')
    log.append({'batch': batch, 'tickets': a.tickets, 'expires': last.isoformat(), 'count': a.count, 'created': today.isoformat(), 'note': a.note})
    json.dump(log, open(LOG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('批次 %d：%d 个码，每个 %d 张，有效期至 %s' % (batch, a.count, a.tickets, last.isoformat()))
    print('已写入', os.path.relpath(name, ROOT))
    for c in codes[:5]:
        print('  ' + c)
    if len(codes) > 5:
        print('  …')


if __name__ == '__main__':
    main()
