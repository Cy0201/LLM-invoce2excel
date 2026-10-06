#!/usr/bin/env python3
"""宣传片配乐：全部用 numpy 合成（无版权素材），120 BPM，和 promo.js 的时间线逐点对齐。
用法：python3 promo/music.py <输出.wav>
"""
import os
import sys

import json
import subprocess

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 44100
DUR = 20.6
N = int(SR * DUR)
HERE = os.path.dirname(os.path.abspath(__file__))
rs = np.random.RandomState(5)

dry = np.zeros((N, 2))   # 鼓、音效
syn = np.zeros((N, 2))   # 铺底、贝斯、琶音：受底鼓侧链压缩
send = np.zeros((N, 2))  # 混响发送


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def tt(n):
    return np.arange(n) / SR


def put(bus, sig, t, gain=1.0, pan=0.0, rev=0.0):
    i = int(round(t * SR))
    if i >= N:
        return
    sig = sig[:N - i] * gain
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    bus[i:i + len(sig), 0] += sig * l * 1.414
    bus[i:i + len(sig), 1] += sig * r * 1.414
    if rev:
        send[i:i + len(sig), 0] += sig * l * rev
        send[i:i + len(sig), 1] += sig * r * rev


def lp(x, f, order=2):
    b, a = signal.butter(order, min(f, SR / 2 - 100) / (SR / 2), 'low')
    return signal.lfilter(b, a, x)


def hp(x, f, order=2):
    b, a = signal.butter(order, f / (SR / 2), 'high')
    return signal.lfilter(b, a, x)


def bp(x, f1, f2, order=2):
    b, a = signal.butter(order, [f1 / (SR / 2), min(f2, SR / 2 - 100) / (SR / 2)], 'band')
    return signal.lfilter(b, a, x)


def env_ar(n, a, r):
    e = np.ones(n)
    na, nr = int(a * SR), int(r * SR)
    if na:
        e[:na] = np.linspace(0, 1, na)
    if nr:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def saw(f, n, phase=0.0):
    t = tt(n)
    k_max = max(1, min(28, int(14000 / f)))
    out = np.zeros(n)
    for k in range(1, k_max + 1):
        out += np.sin(2 * np.pi * k * f * t + phase * k) / k
    return out


# ---------- 乐器 ----------
def pad(chord, t0, t1, gain=.06, cut=1500, att=.5, rel=.9):
    n = int((t1 - t0 + rel) * SR)
    for m in chord:
        for det, pan in ((-.07, -.6), (0, 0), (.07, .6)):
            f = hz(m + det)
            x = saw(f, n, rs.rand() * 6.28)
            x = lp(x, cut)
            e = env_ar(n, att, rel)
            put(syn, x * e, t0, gain / len(chord) * 2.2, pan, rev=.35)


def bass(m, t, d, gain=.22):
    n = int((d + .05) * SR)
    x = np.sin(2 * np.pi * hz(m) * tt(n)) + .25 * np.sin(4 * np.pi * hz(m) * tt(n))
    x = np.tanh(x * 1.4) * env_ar(n, .005, .06)
    put(syn, lp(x, 600), t, gain)


def pluck(m, t, gain=.12, pan=0.0, dec=.16, rev=.4):
    n = int(SR * (dec * 5))
    tm = tt(n)
    f = hz(m)
    x = (np.sin(2 * np.pi * f * tm + .8 * np.sin(2 * np.pi * f * 2 * tm) * np.exp(-tm / .05))
         + .3 * np.sin(4 * np.pi * f * tm)) * np.exp(-tm / dec)
    x[:60] *= np.linspace(0, 1, 60)
    put(syn, x, t, gain, pan, rev)


def bell(m, t, gain=.12, pan=0.0, dur=2.2, rev=.6, bus=None):
    n = int(SR * dur * 1.4)
    tm = tt(n)
    f = hz(m)
    x = np.zeros(n)
    for ratio, amp, dec in ((1, 1, 1.0), (2.01, .5, .6), (2.76, .35, .4), (4.07, .22, .25), (5.43, .14, .15)):
        x += amp * np.sin(2 * np.pi * f * ratio * tm) * np.exp(-tm / (dec * dur / 2))
    x[:40] *= np.linspace(0, 1, 40)
    put(dry if bus is None else bus, x, t, gain, pan, rev)


def kick(t, gain=.75):
    n = int(SR * .5)
    tm = tt(n)
    f = 44 + 110 * np.exp(-tm / .028)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-tm / .26)
    x[:int(.004 * SR)] += rs.randn(int(.004 * SR)) * .3
    put(dry, np.tanh(x * 1.6), t, gain)


KICKS = []


def kk(t, gain=.75):
    KICKS.append(t)
    kick(t, gain)


def clap(t, gain=.32):
    n = int(SR * .35)
    tm = tt(n)
    e = np.exp(-tm / .11)
    for d in (.0, .011, .022):
        i = int(d * SR)
        e[i:i + int(.006 * SR)] += .8
    x = bp(rs.randn(n), 900, 4200) * e
    put(dry, x, t, gain, 0, rev=.5)


def hat(t, gain=.09, dec=.032, pan=.25):
    n = int(SR * dec * 6)
    x = hp(rs.randn(n), 7500) * np.exp(-tt(n) / dec)
    put(dry, x, t, gain, pan)


def crash(t, gain=.25, dec=1.1, rev=.4):
    n = int(SR * dec * 3)
    x = hp(rs.randn(n), 3500) * np.exp(-tt(n) / dec)
    put(dry, x, t, gain, 0, rev)
    return x


def noise_sweep(t0, t1, f0, f1, gain, shape='up', bus=None):
    n = int((t1 - t0) * SR)
    x = rs.randn(n)
    out = np.zeros(n)
    blk = 1024
    for i in range(0, n, blk):
        p = i / n
        fc = f0 * (f1 / f0) ** p
        seg = x[max(0, i - 512):i + blk]
        y = bp(seg, fc * .7, fc * 1.4)
        out[i:i + blk] = y[-len(out[i:i + blk]):]
    p = np.linspace(0, 1, n)
    e = p ** 2 if shape == 'up' else np.sin(np.pi * p) ** 1.5
    put(dry if bus is None else bus, out * e, t0, gain, 0, rev=.3)


def sub_boom(t, gain=.9, f0=60, f1=34, dec=1.0):
    n = int(SR * dec * 2.5)
    tm = tt(n)
    f = f1 + (f0 - f1) * np.exp(-tm / .18)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tm / dec)
    put(dry, np.tanh(x * 1.3), t, gain)


def rev_cymbal(t_end, length=.8, gain=.22):
    n = int(SR * length)
    x = hp(rs.randn(n), 3000) * np.exp(-tt(n) / .35)
    x = x[::-1]
    put(dry, x, t_end - length, gain, 0, rev=.3)


def pop(t, m, gain=.16, pan=0.0):
    """蜡封弹出：短促的木质「啵」"""
    n = int(SR * .18)
    tm = tt(n)
    f = hz(m) * (1 + 1.2 * np.exp(-tm / .01))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tm / .045)
    put(dry, x, t, gain, pan, rev=.25)


def thud(t, gain=.9):
    """盖章"""
    sub_boom(t, gain * .9, 90, 38, .45)
    n = int(SR * .12)
    x = lp(rs.randn(n), 1800) * np.exp(-tt(n) / .02)
    put(dry, x, t, gain * .6, 0, rev=.4)
    n = int(SR * .2)
    x = np.sin(2 * np.pi * 190 * tt(n)) * np.exp(-tt(n) / .05)
    put(dry, x, t, gain * .35)


def ding(t, k):
    """抽卡券到账：两声上行的亮音，越数越高"""
    base = [79, 81, 84, 86, 88, 91, 93, 96, 98, 100][min(k, 9)]
    bell(base, t, .07, .3, dur=.9, rev=.35)
    bell(base + 5, t + .05, .055, .35, dur=1.0, rev=.35)


def swish(t, d=.6, gain=.1):
    noise_sweep(t, t + d, 2500, 9000, gain, 'arch')
    for j, m in enumerate((96, 100, 103, 108)):
        bell(m, t + d * (.2 + j * .12), .025, -.5 + j * .3, dur=1.0, rev=.6)


# ---------- 和弦 ----------
FMAJ9 = [53, 57, 60, 64, 67]
DM9 = [50, 53, 57, 60, 64]
BBMAJ9 = [46, 50, 53, 57, 60]
CSUS = [48, 53, 55, 60, 62]
DBMAJ7S11 = [49, 53, 56, 60, 67]
GM9 = [46, 50, 53, 57, 62]
C7SUS = [48, 53, 55, 58, 62]
FMAJ9_HI = [53, 57, 60, 64, 67, 72]
SCALE = [65, 67, 69, 72, 74, 76, 77, 79, 81, 84, 86, 88, 89, 91]

# ---------- A 0–3：开场 ----------
pad(FMAJ9, 0.0, 3.0, gain=.05, cut=1100, att=1.2, rel=.6)
A_T = [0.45, 0.72, 0.95, 1.14, 1.3, 1.44, 1.56, 1.67, 1.78, 1.89, 2.02]
for j, t in enumerate(A_T):
    bell(SCALE[j % len(SCALE)] + 12, t, .045, (-1) ** j * .4, dur=.8, rev=.6)
bell(65, 2.2, .14, 0, dur=3, rev=.7)
bell(77, 2.2, .07, 0, dur=3, rev=.7)
sub_boom(2.2, .35, 70, 40, .8)
noise_sweep(2.6, 3.3, 600, 9000, .16, 'arch')       # 镭射色带扫过

# ---------- B 3–7：答题 ----------
pad(DM9, 3.0, 5.0, gain=.05, cut=1600)
pad(BBMAJ9, 5.0, 7.0, gain=.05, cut=1900)
for i in range(8):                                   # 3.0–6.5 每拍底鼓
    t = 3.0 + i * .5
    kk(t, .55)
    if i % 2 == 1:
        clap(t, .22)
for i in range(15):
    hat(3.25 + i * .25, .07)
for i in range(30):                                  # 十六分琶音
    t = 3.0 + i * .125
    ch = DM9 if t < 5 else BBMAJ9
    pluck(ch[[0, 2, 4, 1, 3, 2, 4, 1][i % 8]] + 12, t, .06, (-1) ** i * .35)
    if i % 4 == 0:
        bass((38 if t < 5 else 34), t, .45)
# 抽卡券到账：和 promo.js 的 ROUNDS 同一套算法
B_T = [3.0, 4.5, 5.0, 5.5, 5.75, 6.0, 6.25, 6.375, 6.5, 6.625]
for r, t0 in enumerate(B_T):
    dur = (B_T[r + 1] if r + 1 < len(B_T) else 6.75) - t0
    pick = 3.9 if r == 0 else t0 + dur * .45
    fly = .55 if r == 0 else max(.3, min(.45, dur * 1.6))
    pluck(74, pick, .05, 0, .08)                     # 点选
    ding(pick + fly, r)
# 真人发音：直接取 app 里的录音
def voice(word_no):
    js = open(os.path.join(HERE, '..', 'src', 'js', 'audio-clips.js'), encoding='utf-8').read()
    clips = json.loads(js[js.index('{'):js.rindex('}') + 1])
    import base64
    mp3 = base64.b64decode(clips[str(word_no)])
    raw = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', str(SR), 'pipe:1'], input=mp3, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float64) / 32768


put(dry, voice(3), 2.24, .62, 0, rev=.25)      # still（词流停下）
put(dry, voice(14), 4.52, .5, -.1, rev=.2)     # wonder
put(dry, voice(4), 5.02, .5, .1, rev=.2)       # offer

# app 的音效（tools/sfx.py），视频和小工具用同一套声音
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import sfx as FX  # noqa: E402


def fx(name, t, gain, pan=0.0, rev=0.0):
    put(dry, getattr(FX, 's_' + name)(), t, gain, pan, rev)


fx('ok', 3.9, .45)                  # 第一题答对
fx('open', 6.92, .75)               # 拆开
fx('charge', 6.95, .6)              # 蓄力
fx('r5', 8.0, .85)                  # 传说揭晓
fx('stamp', 8.55, .45)              # 卡上的秘封
for k in range(7):
    fx('flick', 10.5 + k * .5, .5, (-1) ** k * .3)
fx('r6', 13.5, .85)                 # 隐藏款
fx('stamp', 17.5, 1.0)              # 盖章
fx('r3', 17.52, .4)
# 吸入 + 蓄力
noise_sweep(6.0, 8.0, 300, 7000, .2, 'up')
rev_cymbal(7.0, .35, .18)
for i in range(16):                                  # 军鼓滚奏渐强
    t = 7.0 + i * .0625
    clap(t, .05 + .2 * (i / 15) ** 2)
pad(CSUS, 7.0, 8.0, gain=.04, cut=900, att=.8, rel=.2)
n = int(SR * 1.0)                                    # 上扬的正弦
f = 200 * (6 ** (tt(n) / 1.0))
put(dry, np.sin(2 * np.pi * np.cumsum(f) / SR) * (tt(n) / 1.0) ** 2, 7.0, .05, 0, rev=.4)

# ---------- C/D 8–13.5：揭晓 + 七个等级 ----------
sub_boom(8.0, .6, 62, 32, 1.3)
crash(8.0, .22, .8, .35)
for m in FMAJ9 + [72, 76]:
    pluck(m, 8.0, .06, 0, .5, .6)
prog = [(8.0, 10.0, FMAJ9, 41), (10.0, 12.0, DM9, 38), (12.0, 13.5, BBMAJ9, 34)]
for t0, t1, ch, root in prog:
    pad(ch, t0, t1, gain=.06, cut=2200, att=.05, rel=.3)
    t = t0
    while t < t1 - 1e-6:
        bass(root if int((t - t0) / .25) % 4 != 3 else root + 12, t, .22)
        t += .25
for i in range(11):                                   # 8.0–13.0 四拍底鼓
    t = 8.0 + i * .5
    kk(t, .8)
    if i % 2 == 1:
        clap(t, .3)
for i in range(22):
    hat(8.25 + i * .25, .08)
    hat(8.125 + i * .25, .035, .02, -.3)
for i in range(44):
    t = 8.0 + i * .125
    ch = FMAJ9 if t < 10 else DM9 if t < 12 else BBMAJ9
    pluck(ch[[0, 2, 4, 1, 3, 2, 4, 1][i % 8]] + 12, t, .05, (-1) ** i * .4)
# 七张卡依次落位：上行的钟声
for k, m in enumerate([72, 74, 76, 79, 81, 84]):
    bell(m, 10.5 + k * .5, .1, (-1) ** k * .3, dur=1.6, rev=.6)
    if k:
        noise_sweep(10.5 + k * .5 - .12, 10.5 + k * .5 + .05, 1500, 7000, .05, 'up')
# 13.5 隐藏款：鼓停，暗色和弦 + 低沉的一击 + 高处闪烁
swish(13.55, .6, .08)                                 # 光缝扫过
kick(14.0, .45)

# ---------- E 14.5–17.5：蜡封 ----------
pad(GM9, 14.5, 16.5, gain=.055, cut=1800)
pad(C7SUS, 16.5, 17.5, gain=.05, cut=1200, rel=.3)
for i in range(5):
    t = 14.5 + i * .5
    kk(t, .65)
    if i % 2 == 1:
        clap(t, .22)
for i in range(9):
    hat(14.75 + i * .25, .07)
for j in range(10):
    pop(14.45 + j * .05, [60, 62, 65, 67, 69, 72, 74, 77, 79, 81][j], .14, (-1) ** j * .5)
for k, m in enumerate([72, 76, 79, 84]):             # 素封 珍封 金封 秘封
    bell(m, 15.0 + k * .5, .11, 0, dur=1.6, rev=.6)
    bell(m + 7, 15.0 + k * .5, .04, .3, dur=1.2, rev=.6)
t = 14.5
while t < 16.75 - 1e-6:
    bass(43 if t < 16.5 else 36, t, .22, .18)
    t += .25
noise_sweep(16.6, 17.5, 400, 8000, .16, 'up')
rev_cymbal(17.5, .7, .2)

# ---------- F 17.5–20：盖章 + 收尾 ----------
thud(17.5, .6)
crash(17.5, .14, 1.0, .45)
pad(FMAJ9_HI, 17.5, 19.9, gain=.07, cut=2600, att=.02, rel=1.2)
bass(29, 17.5, 2.2, .2)
for j, m in enumerate([77, 81, 84, 88, 89]):
    bell(m, 17.5 + j * .11, .07, -.4 + j * .2, dur=2.5, rev=.7)
swish(17.95, .65, .07)
swish(18.9, .6, .06)
bell(89, 19.0, .05, .2, dur=2, rev=.8)

# ---------- 混音 ----------
# 侧链：底鼓压一下铺底，带出律动
duck = np.ones(N)
tm = tt(int(.4 * SR))
curve = 1 - .55 * np.exp(-tm / .09)
for t in KICKS:
    i = int(t * SR)
    j = min(N, i + len(curve))
    duck[i:j] = np.minimum(duck[i:j], curve[:j - i])
syn *= duck[:, None]

# 混响：衰减噪声脉冲
ir_n = int(SR * 2.6)
ir_t = tt(ir_n)
irs = []
for seed in (1, 2):
    r = np.random.RandomState(seed).randn(ir_n) * np.exp(-ir_t / .55)
    irs.append(lp(r, 6000) * (ir_t > .012))
wet = np.stack([signal.fftconvolve(send[:, c], irs[c])[:N] for c in range(2)], 1)
wet = hp(wet.T, 180).T * .16

mix = dry + syn + wet
mix = hp(mix.T, 28).T
mix /= np.max(np.abs(mix)) + 1e-9
mix = np.tanh(mix * 1.6) / np.tanh(1.6)
end = int(20.0 * SR)
mix = mix[:end]
fo = int(.45 * SR)
mix[-fo:] *= np.linspace(1, 0, fo)[:, None] ** 1.5
mix *= .89 / np.max(np.abs(mix))
wavfile.write(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'music.wav'), SR, (mix * 32767).astype(np.int16))
print('music ok', mix.shape[0] / SR, 's')
