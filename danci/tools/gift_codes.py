#!/usr/bin/env python3
"""兑换码生成（离线校验、前端不含任何造码密钥）。

原理：所有码在这里一次生成（12 位随机 Crockford Base32，60 位熵），
小工具里只放每个码的「加盐 SHA-256 迭代 4096 次」指纹（src/js/gift-db.js）。
看得到代码也推不出码；要撞出一个能用的码，算力需求远超个人电脑和显卡。
代价：新增的码要写进小工具，所以发码前要重新打包上传。为此一次把一整年的码都生成好。

用法：
  python3 tools/gift_codes.py --year                    # 生成一年的周码：每周 30 个，每个 10 张
  python3 tools/gift_codes.py --year --tickets 8 --count 20 --start 2026-10-05 --weeks 52
  python3 tools/gift_codes.py --extra --tickets 5 --days 3 --count 50 --note "直播"   # 追加一批临时码（要重新打包）
  python3 tools/gift_codes.py --import gift-codes/旧码.txt --batch 1 --tickets 10 --from 2026-10-06 --to 2026-10-12
  python3 tools/gift_codes.py --list

规则：
- 每周一批：从周一起生效，到下周三截止（多留 3 天）。同一批每台手机只能领一次，
  所以一个码可以直接发到粉丝群；每周可以再领一次新一周的码。
- 码写在 gift-codes/（不进仓库，务必自己另存一份）；仓库里只有指纹和批次记录。
"""
import argparse
import base64
import csv
import datetime
import hashlib
import json
import os
import re
import secrets
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_JS = os.path.join(ROOT, 'src', 'js', 'gift-db.js')
GIFT_JS = os.path.join(ROOT, 'src', 'js', 'gift.js')
LOG = os.path.join(ROOT, 'tools', 'gift_batches.json')
OUT = os.path.join(ROOT, 'gift-codes')
AB = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
EPOCH = datetime.date(2026, 1, 1)
IT = 4096
GRACE = 3


def day(d):
    return (d - EPOCH).days


def fmt(c):
    return c[:4] + '-' + c[4:8] + '-' + c[8:]


def clean(s):
    s = s.upper().replace('O', '0').replace('I', '1').replace('L', '1').replace('U', 'V')
    return re.sub('[^0-9A-Z]', '', s)


def digest(code, salt):
    h = hashlib.sha256((salt + ':' + code).encode()).digest()
    for _ in range(IT - 1):
        h = hashlib.sha256(h).digest()
    return base64.b64encode(h[:12]).decode()


def new_code(used):
    while True:
        c = ''.join(secrets.choice(AB) for _ in range(12))
        if c not in used:
            used.add(c)
            return c


def load_db():
    if not os.path.exists(DB_JS):
        return None
    js = open(DB_JS, encoding='utf-8').read()
    return json.loads(js[js.index('{'):js.rindex('}') + 1])


def save_db(db):
    db['w'].sort(key=lambda w: (w[0], w[3]))
    body = json.dumps(db, ensure_ascii=False, separators=(',', ':'))
    open(DB_JS, 'w', encoding='utf-8').write(
        '/* 兑换码指纹（加盐 SHA-256 × %d，取前 96 位），由 tools/gift_codes.py 生成；不含任何码本身。\n'
        ' * w: [生效日, 截止日（含）, 张数, 批次, 指纹串]，日期为 2026-01-01 起的天数 */\nwindow.GIFT_DB=%s;\n' % (IT, body))


def add_batch(db, key, start, end, tickets, codes):
    assert not any(w[3] == key for w in db['w']), '批次 %s 已存在' % key
    db['w'].append([day(start), day(end), tickets, key, ''.join(digest(c, db['s']) for c in codes)])


def log_batch(key, start, end, tickets, count, note):
    log = json.load(open(LOG, encoding='utf-8')) if os.path.exists(LOG) else []
    log.append({'batch': key, 'tickets': tickets, 'from': start.isoformat(), 'expires': end.isoformat(), 'count': count,
                'created': datetime.date.today().isoformat(), 'note': note})
    json.dump(log, open(LOG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def verify(samples):
    """用 app 里的 JS 校验，确保两边算法一致。samples: [(code, 期望批次)]，在各自有效期内的码"""
    js = open(DB_JS, encoding='utf-8').read() + open(GIFT_JS, encoding='utf-8').read()
    r = subprocess.run(['node', '-e', 'global.window={};' + js + ';const s=JSON.parse(process.argv[1]);'
                        'console.log(JSON.stringify(s.map(x=>{const r=window.GiftCode.parse(x[0]);return r.ok?r.batch:r.err;})))',
                        json.dumps(samples)], capture_output=True, text=True)
    got = json.loads(r.stdout or 'null')
    want = [s[1] for s in samples]
    assert got == want, '校验失败：%s / %s %s' % (got, want, r.stderr)


def write_codes(name, rows, title):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    with open(path + '.csv', 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['批次', '生效日', '截止日（含）', '每个码张数', '兑换码'])
        for r in rows:
            w.writerow(r)
    with open(path + '.txt', 'w', encoding='utf-8') as f:
        f.write(title + '\n兑换方式：长按首页卡片上的蜡封（或连点三下），输入兑换码。同一批每台手机限领一次。\n')
        last = None
        for r in rows:
            if r[0] != last:
                f.write('\n【%s】%s ～ %s · 每个 %s 张\n' % (r[0], r[1], r[2], r[3]))
                last = r[0]
            f.write(r[4] + '\n')
    return path


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--year', action='store_true', help='生成一年的周码')
    g.add_argument('--extra', action='store_true', help='追加一批临时码')
    g.add_argument('--import', dest='imp', help='把已有码文件（每行一个码）加入指纹库')
    g.add_argument('--list', action='store_true')
    ap.add_argument('--tickets', type=int, default=10)
    ap.add_argument('--count', type=int, default=30)
    ap.add_argument('--start', help='第一周的周一（默认本周一）')
    ap.add_argument('--weeks', type=int, default=52)
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--from', dest='frm')
    ap.add_argument('--to')
    ap.add_argument('--batch')
    ap.add_argument('--note', default='')
    ap.add_argument('--force', action='store_true', help='--year 时覆盖已有指纹库（之前发出的码全部作废）')
    a = ap.parse_args()

    if a.list:
        for b in (json.load(open(LOG, encoding='utf-8')) if os.path.exists(LOG) else []):
            print('批次 %-5s %2d 张  %s ～ %s  %4d 个  %s' % (b['batch'], b['tickets'], b.get('from', ''), b['expires'], b['count'], b.get('note', '')))
        return
    assert 1 <= a.tickets <= 99
    db = load_db()
    if a.year:
        if db and db['w'] and not a.force:
            # 保留已有批次，只追加周码
            assert not any(str(w[3]).startswith('w') for w in db['w']), '已经有周码了；确实要重来请加 --force（已发出的码会作废）'
        if not db or a.force:
            db = {'s': secrets.token_urlsafe(18), 'it': IT, 'w': []}
        today = datetime.date.today()
        mon = datetime.date.fromisoformat(a.start) if a.start else today - datetime.timedelta(days=today.weekday())
        used, rows, samples = set(), [], []
        for k in range(a.weeks):
            st = mon + datetime.timedelta(weeks=k)
            en = st + datetime.timedelta(days=6 + GRACE)
            key = 'w%02d' % (k + 1)
            codes = [new_code(used) for _ in range(a.count)]
            add_batch(db, key, st, en, a.tickets, codes)
            rows += [[key, st.isoformat(), en.isoformat(), a.tickets, fmt(c)] for c in codes]
            if st <= today <= en:
                samples.append((codes[0], key))
        save_db(db)
        log_batch('w01-w%02d' % a.weeks, mon, mon + datetime.timedelta(weeks=a.weeks - 1, days=6 + GRACE), a.tickets, a.count * a.weeks, a.note or '全年周码')
        verify(samples + [('ZZZZ-ZZZZ-ZZZZ', 'sign')])
        last = mon + datetime.timedelta(weeks=a.weeks - 1, days=6)
        p = write_codes('全年周码_%s至%s' % (mon.strftime('%Y%m%d'), last.strftime('%Y%m%d')), rows,
                        '单词手账 兑换码 · 每周一批（周一生效，下周三截止）· 每个码 %d 张抽卡券' % a.tickets)
        print('%d 周 × %d 个码，已写入 %s.csv / .txt' % (a.weeks, a.count, os.path.relpath(p, ROOT)))
    elif a.extra:
        assert db, '先生成指纹库（--year）'
        today = datetime.date.today()
        en = today + datetime.timedelta(days=a.days - 1)
        key = a.batch or 'x%d' % (sum(1 for w in db['w'] if str(w[3]).startswith('x')) + 1)
        used = set()
        codes = [new_code(used) for _ in range(a.count)]
        add_batch(db, key, today, en, a.tickets, codes)
        save_db(db)
        log_batch(key, today, en, a.tickets, a.count, a.note)
        verify([(codes[0], key)])
        p = write_codes('临时码_%s_%d张_至%s' % (key, a.tickets, en.strftime('%m%d')), [[key, today.isoformat(), en.isoformat(), a.tickets, fmt(c)] for c in codes],
                        '单词手账 兑换码 · 批次 %s · %s' % (key, a.note))
        print('批次 %s：%d 个码，已写入 %s.csv / .txt（记得重新打包上传）' % (key, a.count, os.path.relpath(p, ROOT)))
    else:
        assert db, '先生成指纹库（--year）'
        codes = [clean(l) for l in open(a.imp, encoding='utf-8') if len(clean(l)) == 12 and re.fullmatch(r'[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}', l.strip())]
        st, en = datetime.date.fromisoformat(a.frm), datetime.date.fromisoformat(a.to)
        add_batch(db, a.batch, st, en, a.tickets, codes)
        save_db(db)
        print('导入批次 %s：%d 个码' % (a.batch, len(codes)))
        if st <= datetime.date.today() <= en:
            verify([(codes[0], a.batch)])


if __name__ == '__main__':
    main()
