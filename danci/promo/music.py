#!/usr/bin/env python3
"""宣传片配乐 v2：全部用 numpy 合成（无版权素材），120 BPM（一拍 0.5 秒），和 promo.js 的时间线逐点对齐。
编制：柔和钢琴、温暖弦乐、八音盒主旋律（贯穿全片的记忆点）、合唱、低音、轻打击；音效复用 app 的 tools/sfx.py。
情绪线：悬念开场 → 轻快答题 → 蓄力 → 揭晓爆发 → 七个等级上行 → 隐藏款前骤停（心跳 + 暗色和弦）→ 火漆 → 盖章后大三和弦落地。
用法：python3 promo/music.py <输出.wav>
"""
import json
import os
import subprocess
import sys

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 44100
DUR = 21.0
N = int(SR * DUR)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import sfx as FX  # noqa: E402

rs = np.random.RandomState(8)
dry = np.zeros((N, 2))    # 打击、音效、人声
syn = np.zeros((N, 2))    # 弦乐、钢琴、低音：受底鼓侧链，拍子起来时会「呼吸」
send = np.zeros((N, 2))   # 混响发送
KICKS = []


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def tt(n):
    return np.arange(n) / SR


def put(bus, x, t, g=1.0, pan=0.0, rev=0.0):
    i = int(round(t * SR))
    if i >= N or i + len(x) <= 0:
        return
    if i < 0:
        x, i = x[-i:], 0
    x = x[:N - i] * g
    l, r = np.cos((pan + 1) * np.pi / 4) * 1.414, np.sin((pan + 1) * np.pi / 4) * 1.414
    bus[i:i + len(x), 0] += x * l
    bus[i:i + len(x), 1] += x * r
    if rev:
        send[i:i + len(x), 0] += x * l * rev
        send[i:i + len(x), 1] += x * r * rev


def lp(x, f, o=2):
    b, a = signal.butter(o, min(f, SR / 2 - 200) / (SR / 2), 'low')
    return signal.lfilter(b, a, x)


def hp(x, f, o=2):
    b, a = signal.butter(o, f / (SR / 2), 'high')
    return signal.lfilter(b, a, x)


def env(n, a, r):
    e = np.ones(n)
    na, nr = min(n, int(a * SR)), min(n, int(r * SR))
    if na:
        e[:na] = np.sin(np.linspace(0, np.pi / 2, na)) ** 2
    if nr:
        e[-nr:] *= np.cos(np.linspace(0, np.pi / 2, nr)) ** 2
    return e


# ---------------- 乐器 ----------------
def piano(m, t, vel=.6, dur=2.5, bus=None, rev=.35):
    """柔和钢琴：带轻微非谐的加法合成，高泛音衰减更快，力度越大越亮"""
    f = hz(m)
    tau0 = np.interp(m, [36, 60, 84, 100], [4.5, 2.6, 1.2, .6])
    n = int((dur + .4) * SR)
    x = np.zeros(n)
    tm = tt(n)
    B = .00035
    for k in range(1, 14):
        fk = k * f * np.sqrt(1 + B * k * k)
        if fk > 14000:
            break
        amp = (1 / k ** 1.25) * (vel ** (k * .12))
        x += amp * np.sin(2 * np.pi * fk * tm + rs.rand() * 6.28) * np.exp(-tm / (tau0 / (1 + .35 * (k - 1))))
    att = int(.004 * SR)
    x[:att] *= np.linspace(0, 1, att)
    x += lp(rs.randn(n), 2500) * np.exp(-tm / .012) * .05 * vel           # 槌击
    x *= env(n, 0, .3)
    x = lp(x, 2000 + 4000 * vel)
    put(syn if bus is None else bus, x, t, .22 * vel, np.clip((m - 66) / 30, -.6, .6), rev)


def chord_piano(ms, t, vel=.5, dur=2.2, spread=.012):
    for i, m in enumerate(ms):
        piano(m, t + i * spread, vel * (1 - .06 * i), dur)


def strings(ms, t0, t1, g=.05, att=.7, rel=1.2, cut=2400):
    """温暖弦乐：每个音 5 根略微失谐的锯齿 + 揉弦，低通，铺在立体声两侧"""
    n = int((t1 - t0 + rel) * SR)
    tm = tt(n)
    for m in ms:
        f = hz(m)
        for j, det in enumerate((-.09, -.04, 0, .05, .1)):
            fv = f * 2 ** (det / 12) * (1 + .0025 * np.sin(2 * np.pi * (4.8 + j * .3) * tm + j))
            ph = 2 * np.pi * np.cumsum(fv) / SR
            x = np.zeros(n)
            for k in range(1, min(20, int(9000 / f)) + 1):
                x += np.sin(k * ph) / k
            x = lp(x, cut) * env(n, att, rel)
            put(syn, x, t0, g / len(ms), (j - 2) * .3, .5)


def musicbox(m, t, g=.1, pan=0.0, rev=.55):
    """八音盒：明亮的基音 + 非谐泛音 + 一点金属簧片的咔嗒声"""
    n = int(2.2 * SR)
    tm = tt(n)
    f = hz(m)
    x = (np.sin(2 * np.pi * f * tm) * np.exp(-tm / .9) + .45 * np.sin(2 * np.pi * f * 3.01 * tm) * np.exp(-tm / .35)
         + .2 * np.sin(2 * np.pi * f * 6.24 * tm) * np.exp(-tm / .12))
    x[:30] *= np.linspace(0, 1, 30)
    x += hp(rs.randn(n), 6000) * np.exp(-tm / .004) * .08
    put(dry, x, t, g, pan, rev)


def bass(m, t, d, g=.2):
    n = int((d + .06) * SR)
    tm = tt(n)
    x = np.sin(2 * np.pi * hz(m) * tm) + .18 * np.sin(4 * np.pi * hz(m) * tm)
    x = np.tanh(1.3 * x) * env(n, .008, .08)
    put(syn, lp(x, 500), t, g)


def kick(t, g=.7):
    KICKS.append(t)
    n = int(.45 * SR)
    tm = tt(n)
    f = 42 + 95 * np.exp(-tm / .03)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tm / .24)
    x[:int(.003 * SR)] += rs.randn(int(.003 * SR)) * .15
    put(dry, np.tanh(1.4 * x), t, g)


def clap(t, g=.22):
    n = int(.35 * SR)
    tm = tt(n)
    e = np.exp(-tm / .1)
    for d in (0, .009, .019):
        i = int(d * SR)
        e[i:i + int(.005 * SR)] += .7
    x = FX.bp(rs.randn(n), 900, 5000) * e
    put(dry, x, t, g, 0, .55)


def snap(t, g=.12, pan=.2):
    n = int(.12 * SR)
    x = FX.bp(rs.randn(n), 1800, 6000) * np.exp(-tt(n) / .018)
    put(dry, x, t, g, pan, .5)


def shaker(t, g=.05, pan=.35):
    n = int(.09 * SR)
    tm = tt(n)
    x = hp(rs.randn(n), 6500) * np.sin(np.pi * np.clip(tm / .07, 0, 1)) ** 2
    put(dry, x, t, g, pan, .15)


def riser(t0, t1, g=.18):
    put(dry, FX.noise_sweep(t1 - t0, 300, 8000, 'up', 1.0, .4), t0, g, 0, .35)
    n = int((t1 - t0) * SR)
    tm = tt(n)
    f = 180 * (5 ** (tm / (t1 - t0)))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * (tm / (t1 - t0)) ** 2
    put(dry, x, t0, g * .2, 0, .5)


def rev_swell(t_end, length=.8, g=.2):
    n = int(length * SR)
    x = hp(rs.randn(n), 2500) * np.exp(-tt(n) / .3)
    put(dry, x[::-1], t_end - length, g, 0, .4)


def heartbeat(t, g=.55):
    for d, a in ((0, 1.0), (.22, .7)):
        put(dry, FX.boom(70, 38, .28, 1.0), t + d, g * a)


def fx(name, t, g, pan=0.0, rev=0.0):
    put(dry, getattr(FX, 's_' + name)(), t, g, pan, rev)


def voice(word_no):
    """发音：直接用 app 里的录音"""
    js = open(os.path.join(HERE, '..', 'src', 'js', 'audio-clips.js'), encoding='utf-8').read()
    clips = json.loads(js[js.index('{'):js.rindex('}') + 1])
    import base64
    mp3 = base64.b64decode(clips[str(word_no)])
    raw = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', str(SR), 'pipe:1'],
                         input=mp3, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float64) / 32768


# ---------------- 和声与主旋律 ----------------
F9 = [53, 57, 60, 64, 67]          # Fmaj9
DM9 = [50, 53, 57, 60, 64]
BB9 = [46, 50, 53, 57, 60]          # Bbmaj9
CSUS = [48, 53, 55, 60, 62]
GM9 = [43, 50, 53, 57, 62]
C11 = [48, 55, 58, 62, 65]
DB = [37, 49, 53, 56, 60, 67]       # Dbmaj7#11（隐藏款的暗色）
F_END = [41, 53, 57, 60, 64, 67, 72]
# 主旋律（拍, 音高）：C6 A5 F5 A5 | C6 – D6 C6 | A5 – G5 A5 | F5 ——
MOTIF = [(0, 84), (.5, 81), (1, 77), (1.5, 81), (2, 84), (3, 86), (3.5, 84), (4, 81), (5, 79), (5.5, 81), (6, 77)]


def motif(t0, g=.1, upto=99, octave=0, rev=.55):
    for i, (b, m) in enumerate(MOTIF):
        if i >= upto:
            break
        musicbox(m + octave, t0 + b * .5, g, (-1) ** i * .25, rev)


# ===== A 0–3：悬念开场 + 词流 =====
strings(F9, 0.0, 3.0, g=.045, att=1.6, rel=.8, cut=1600)
motif(0.25, .085, upto=7)                                        # 八音盒主旋律前半句
A_T = [0.45, 0.72, 0.95, 1.14, 1.3, 1.44, 1.56, 1.67, 1.78, 1.89, 2.02]
for j, t in enumerate(A_T):                                      # 词流闪过：很轻的星光
    musicbox(96 + [0, 2, 4, 7, 9][j % 5], t, .018, (-1) ** j * .5, .7)
chord_piano([53, 60, 64, 69], 2.2, .55, 2.2)                     # still 落定
put(dry, voice(3), 2.24, .6, 0, .25)
put(dry, FX.noise_sweep(.7, 600, 9000, 'arch', 1.0, .45), 2.62, .1, 0, .3)   # 镭射色带扫过

# ===== B 3–7：答题，轻快 =====
for i in range(8):
    t = 3.0 + i * .5
    if i % 2 == 0:
        kick(t, .45)
    else:
        snap(t, .13)
for i in range(16):
    shaker(3.0 + i * .25 + (.03 if i % 2 else 0), .045 if i % 2 else .03)
for t0, ch, root in ((3.0, DM9, 38), (5.0, BB9, 34)):
    strings(ch, t0, t0 + 2, g=.035, att=.4, rel=.5, cut=2000)
    for b, v in ((0, .5), (.75, .35), (1.5, .4)):                # 钢琴切分和弦
        chord_piano([m + 12 for m in ch[1:4]], t0 + b, v, .9)
    for b in range(4):
        bass(root, t0 + b * .5, .45, .16)
put(dry, voice(14), 4.52, .5, -.1, .2)                           # wonder
put(dry, voice(4), 5.02, .5, .1, .2)                             # offer
fx('ok', 3.9, .4)
B_T = [3.0, 4.5, 5.0, 5.5, 5.75, 6.0, 6.25, 6.375, 6.5, 6.625]
SCALE = [77, 79, 81, 84, 86, 88, 89, 91, 93, 96]
for r, t0 in enumerate(B_T):                                     # 抽卡券到账：沿音阶往上走
    dur = (B_T[r + 1] if r + 1 < len(B_T) else 6.75) - t0
    pick = 3.9 if r == 0 else t0 + dur * .45
    fly = .55 if r == 0 else max(.3, min(.45, dur * 1.6))
    musicbox(SCALE[r] + 12, pick + fly, .06, .3, .4)

# ===== 蓄力 6–8 =====
riser(6.0, 8.0, .16)
strings(CSUS, 6.5, 8.0, g=.05, att=1.2, rel=.15, cut=3000)
for i in range(16):                                              # 军鼓滚奏渐强
    clap(7.0 + i * .0625, .03 + .16 * (i / 15) ** 2)
fx('open', 6.92, .55)
fx('charge', 6.95, .45)
rev_swell(8.0, .7, .2)

# ===== C/D 8–13：揭晓 + 七个等级 =====
put(dry, FX.boom(62, 30, 1.4, 1.0), 8.0, .75)
fx('r5', 8.0, .7)
for t0, t1, ch, root in ((8.0, 10.0, F9, 41), (10.0, 12.0, DM9, 38), (12.0, 13.0, BB9, 34)):
    strings(ch, t0, t1, g=.06, att=.05, rel=.4, cut=3200)
    t = t0
    while t < t1 - 1e-6:
        bass(root if int((t - t0) / .25) % 4 != 3 else root + 12, t, .22, .2)
        t += .25
    for i in range(int((t1 - t0) / .125)):                       # 钢琴十六分琶音
        piano(ch[[0, 2, 4, 1, 3, 2, 4, 1][i % 8]] + 24, t0 + i * .125, .32, .6)
for i in range(10):
    t = 8.0 + i * .5
    kick(t, .75)
    if i % 2:
        clap(t, .25)
for i in range(20):
    shaker(8.25 + i * .25, .05)
motif(8.0, .09, octave=12)                                       # 主旋律完整一句（高八度）
for k, m in enumerate([77, 81, 84, 86, 89, 93]):                 # 七张卡依次落位：沿主旋律上行
    musicbox(m + 12, 10.5 + k * .5, .1, (-1) ** k * .3, .6)
    fx('flick', 10.5 + k * .5, .35, (-1) ** k * .3)

# ===== 13–14.5：骤停 → 隐藏款 =====
rev_swell(13.5, 1.2, .16)
heartbeat(13.05, .45)
put(dry, FX.boom(55, 26, 2.0, 1.0), 13.5, .8)
fx('r6', 13.5, .65)
strings(DB, 13.5, 14.6, g=.06, att=.05, rel=.7, cut=1500)
heartbeat(14.0, .35)
put(dry, FX.noise_sweep(.6, 2500, 9000, 'arch', 1.0, .4), 13.55, .06, 0, .5)   # 光缝扫过

# ===== E 14.5–17.5：火漆 =====
strings(GM9, 14.5, 16.5, g=.05, att=.3, rel=.4, cut=2200)
strings(C11, 16.5, 17.5, g=.05, att=.2, rel=.2, cut=1800)
for i in range(5):
    t = 14.5 + i * .5
    if i % 2 == 0:
        kick(t, .55)
    else:
        snap(t, .12)
for i in range(9):
    shaker(14.75 + i * .25, .04)
for j in range(10):                                              # 十枚火漆弹出
    FXpop = FX.marimba(hz([60, 62, 65, 67, 69, 72, 74, 77, 79, 81][j]), .3, 1.0)
    put(dry, FXpop, 14.45 + j * .05, .1, (-1) ** j * .5, .3)
for k, m in enumerate([84, 88, 91, 96]):                         # 素封 珍封 金封 秘封
    musicbox(m, 15.0 + k * .5, .1, 0, .6)
    piano(m - 24, 15.0 + k * .5, .35, 1.0)
t = 14.5
while t < 16.75 - 1e-6:
    bass(43 if t < 16.5 else 36, t, .22, .16)
    t += .25
riser(16.7, 17.5, .14)
rev_swell(17.5, .7, .2)

# ===== F 17.5–21：盖章，大三和弦落地 =====
fx('stamp', 17.5, .9)
put(dry, FX.boom(80, 34, 1.4, 1.0), 17.5, .55)
strings(F_END, 17.5, 20.0, g=.08, att=.05, rel=1.4, cut=3600)
put(syn, FX.choir([hz(m) for m in (53, 57, 60, 64, 69)], 3.2, 1.0, .08, 1.4), 17.5, .5, 0, .6)
chord_piano([41, 53, 60, 64, 67, 72], 17.5, .7, 3.2)
bass(29, 17.5, 2.4, .2)
for i, (b, m) in enumerate([(0, 93), (.5, 91), (1, 89), (2, 84)]):   # 主旋律收尾
    musicbox(m, 17.6 + b * .5, .09, (-1) ** i * .3, .7)
for j, m in enumerate((96, 100, 103, 108)):                      # 光缝扫过的亮片
    musicbox(m, 18.0 + j * .12, .03, -.5 + j * .3, .8)
    musicbox(m - 5, 18.95 + j * .12, .025, .5 - j * .3, .8)

# ---------------- 混音 ----------------
duck = np.ones(N)
curve = 1 - .5 * np.exp(-tt(int(.4 * SR)) / .1)
for t in KICKS:
    i = int(t * SR)
    j = min(N, i + len(curve))
    duck[i:j] = np.minimum(duck[i:j], curve[:j - i])
syn *= duck[:, None]

# 混响：立体声去相关的衰减噪声 + 早期反射，25ms 预延迟
irn = int(SR * 3.0)
irt = tt(irn)
irs = []
for seed in (11, 12):
    r = np.random.RandomState(seed)
    ir = r.randn(irn) * np.exp(-irt / .62)
    for d, a in ((.011, .5), (.019, .35), (.027, .3), (.041, .22)):
        ir[int(d * SR)] += a * (1 if seed == 11 else -1)
    ir = lp(ir, 7000)
    ir[:int(.025 * SR)] = 0
    irs.append(ir / np.sqrt((ir ** 2).sum()))
wet = np.stack([signal.fftconvolve(send[:, c], irs[c])[:N] for c in range(2)], 1)
wet = hp(wet.T, 160).T * .9

mix = dry + syn + wet
mix = hp(mix.T, 30).T
# 轻微母带：柔和压缩 + 软限幅
mix /= np.max(np.abs(mix)) + 1e-9
mix = np.tanh(mix * 1.5) / np.tanh(1.5)
end = int(20.0 * SR)
mix = mix[:end]
fo = int(.5 * SR)
mix[-fo:] *= (np.linspace(1, 0, fo) ** 1.6)[:, None]
mix *= .89 / np.max(np.abs(mix))
wavfile.write(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'music.wav'), SR, (mix * 32767).astype(np.int16))
print('music ok %.1fs' % (len(mix) / SR))
