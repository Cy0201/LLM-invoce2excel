#!/usr/bin/env python3
"""音效合成：全部用 numpy 现场合成（无版权素材），输出 src/js/sfx-clips.js（MP3，Base64 内联）。
用法：python3 tools/sfx.py [--wav 目录]     # --wav 时另存一份 wav 方便试听
依赖：numpy scipy，ffmpeg（libmp3lame）
"""
import base64
import os
import subprocess
import sys
import tempfile

import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'src', 'js', 'sfx-clips.js')
rs = np.random.RandomState(11)


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def tt(n):
    return np.arange(n) / SR


def buf(sec):
    return np.zeros(int(sec * SR))


def put(b, x, t, g=1.0):
    i = int(t * SR)
    if i >= len(b):
        return
    x = x[:len(b) - i]
    b[i:i + len(x)] += x * g


def lp(x, f, o=2):
    b, a = signal.butter(o, min(f, SR / 2 - 200) / (SR / 2), 'low')
    return signal.lfilter(b, a, x)


def hp(x, f, o=2):
    b, a = signal.butter(o, f / (SR / 2), 'high')
    return signal.lfilter(b, a, x)


def bp(x, f1, f2, o=2):
    b, a = signal.butter(o, [f1 / (SR / 2), min(f2, SR / 2 - 200) / (SR / 2)], 'band')
    return signal.lfilter(b, a, x)


def reverb(x, sec=1.6, wet=.3, damp=5000, pre=.015):
    n = int(sec * SR)
    ir = np.random.RandomState(3).randn(n) * np.exp(-tt(n) / (sec / 5))
    ir = lp(ir, damp)
    ir[:int(pre * SR)] = 0
    ir /= np.sqrt((ir ** 2).sum())
    y = signal.fftconvolve(x, ir)[:len(x)]
    return x + hp(y, 200) * wet


# ---------- 音色 ----------
def bell(f, dur=1.2, amp=1.0, bright=1.0):
    """玻璃钟：非整数泛音，高泛音衰减更快"""
    n = int(dur * SR)
    t = tt(n)
    x = np.zeros(n)
    for r, a, d in ((1, 1, 1), (2.0, .45, .55), (3.01, .25 * bright, .35), (4.17, .16 * bright, .22), (5.43, .1 * bright, .14), (8.9, .05 * bright, .08)):
        if f * r < SR / 2 - 500:
            x += a * np.sin(2 * np.pi * f * r * t) * np.exp(-t / (d * dur / 2.2))
    x[:30] *= np.linspace(0, 1, 30)
    return x * amp


def celesta(f, dur=1.0, amp=1.0):
    n = int(dur * SR)
    t = tt(n)
    x = np.sin(2 * np.pi * f * t + 1.2 * np.sin(2 * np.pi * f * 4 * t) * np.exp(-t / .03)) * np.exp(-t / (dur / 3))
    x[:20] *= np.linspace(0, 1, 20)
    return x * amp


def marimba(f, dur=.5, amp=1.0):
    n = int(dur * SR)
    t = tt(n)
    x = np.sin(2 * np.pi * f * t) * np.exp(-t / .16) + .3 * np.sin(2 * np.pi * f * 3.93 * t) * np.exp(-t / .03)
    x[:40] *= np.linspace(0, 1, 40)
    return lp(x, 3000) * amp


def saw(f, n, vib=0.0, vr=5.0):
    t = tt(n)
    ph = 2 * np.pi * f * t + (vib * np.sin(2 * np.pi * vr * t) if vib else 0)
    x = np.zeros(n)
    for k in range(1, min(24, int(12000 / f)) + 1):
        x += np.sin(k * ph + rs.rand() * 0) / k
    return x


def choir(freqs, dur, amp=1.0, att=.25, rel=.8):
    """合唱铺底：锯齿波过「啊」的共振峰"""
    n = int(dur * SR)
    x = np.zeros(n)
    for f in freqs:
        for det in (-.004, 0, .005):
            x += saw(f * (1 + det), n, vib=.012 * f / f * 2, vr=5 + rs.rand())
    y = bp(x, 600, 900) * 1.0 + bp(x, 1000, 1300) * .6 + bp(x, 2400, 2900) * .25
    e = np.ones(n)
    na, nr = int(att * SR), int(rel * SR)
    e[:na] = np.linspace(0, 1, na) ** 2
    e[-nr:] *= np.linspace(1, 0, nr) ** 1.5
    return y * e / len(freqs) * amp


def boom(f0=70, f1=36, dur=1.2, amp=1.0):
    n = int(dur * SR)
    t = tt(n)
    f = f1 + (f0 - f1) * np.exp(-t / .15)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (dur / 3))
    x[:int(.003 * SR)] += rs.randn(int(.003 * SR)) * .4
    return np.tanh(x * 1.5) * amp


def noise_sweep(dur, f0, f1, shape='up', amp=1.0, q=.35):
    n = int(dur * SR)
    x = rs.randn(n)
    out = np.zeros(n)
    blk = 512
    for i in range(0, n, blk):
        p = i / n
        fc = f0 * (f1 / f0) ** p
        seg = x[max(0, i - 1024):i + blk]
        y = bp(seg, fc * (1 - q), fc * (1 + q))
        out[i:i + blk] = y[-len(out[i:i + blk]):]
    p = np.linspace(0, 1, n)
    e = {'up': p ** 2, 'down': (1 - p) ** 2, 'arch': np.sin(np.pi * p) ** 1.5}[shape]
    return out * e * amp


def glitter(dur, count, lo=84, hi=108, amp=.12, seed=1, decay=1.0):
    """亮晶晶：随机的高音小钟，越往后越稀"""
    r = np.random.RandomState(seed)
    b = buf(dur + .8)
    for i in range(count):
        t = dur * (r.rand() ** 1.6)
        m = lo + r.randint(0, hi - lo)
        m = m - m % 12 + min([0, 2, 4, 7, 9, 12], key=lambda s: abs(s - m % 12))   # 落在五声音阶上
        put(b, celesta(hz(m), .5 + r.rand() * .4), t, amp * (.4 + .6 * r.rand()) * (1 - t / dur * .6 * decay))
    return b


def crackle(dur, density, amp=1.0, seed=5):
    """锡纸揉动：一串随机的细小爆裂"""
    r = np.random.RandomState(seed)
    b = buf(dur)
    n = int(dur * density)
    for i in range(n):
        t = dur * (r.rand() ** .7)
        m = int(SR * (.002 + r.rand() * .006))
        put(b, r.randn(m) * np.exp(-tt(m) / .0015) * (.3 + r.rand()), t)
    return bp(b, 1800, 9000) * amp


def finish(x, peak, tail=.08):
    x = hp(x, 35)
    n = int(tail * SR)
    x[-n:] *= np.linspace(1, 0, n)
    return x / (np.max(np.abs(x)) + 1e-9) * peak


# ---------- 音效 ----------
def s_ok():
    b = buf(1.0)
    put(b, bell(hz(88), .9, .9), 0)          # E6
    put(b, bell(hz(95), 1.0, .8), .075)      # B6
    put(b, glitter(.4, 5, 96, 108, .08, 2), .1)
    return finish(reverb(b, 1.2, .25), .55)


def s_bad():
    b = buf(.55)
    put(b, marimba(hz(57), .45), 0)          # A3
    put(b, marimba(hz(52), .5), .11)         # E3
    return finish(reverb(b, .8, .12), .5)


def s_done():
    b = buf(1.6)
    for i, m in enumerate((84, 88, 91, 96)):
        put(b, bell(hz(m), 1.1, .8), i * .075)
    put(b, glitter(.9, 14, 96, 112, .1, 4), .25)
    return finish(reverb(b, 1.5, .3), .6)


def s_open():
    """拆开卡包：锡纸窸窣 → 一声撕开 → 气流 + 星光"""
    b = buf(1.5)
    cr = crackle(.42, 160, .9) * np.linspace(.3, 1, int(.42 * SR))
    put(b, cr, 0)
    tear = noise_sweep(.26, 7000, 1400, 'down', 1.4, .45)
    tear *= 1 + .6 * np.sign(np.sin(2 * np.pi * 38 * tt(len(tear))))   # 纤维一根根断开的颗粒感
    put(b, tear, .36)
    put(b, noise_sweep(.55, 500, 5000, 'arch', .5, .5), .5)            # 打开时的气流
    put(b, bell(hz(91), 1.0, .35), .62)
    put(b, glitter(.7, 16, 91, 110, .12, 6), .62)
    return finish(reverb(b, 1.4, .22), .8)


def s_charge():
    """蓄力：上扬的气流 + 越来越快的颤音 + 两声心跳"""
    d = 1.05
    b = buf(d + .1)
    n = int(d * SR)
    t = tt(n)
    put(b, noise_sweep(d, 300, 7000, 'up', .55, .4), 0)
    f = 220 * (4 ** (t / d))
    trem = .5 + .5 * np.sin(2 * np.pi * np.cumsum(6 + 26 * (t / d) ** 2) / SR)
    sweep = np.sin(2 * np.pi * np.cumsum(f) / SR) * trem * (t / d) ** 1.5
    put(b, sweep, 0, .25)
    put(b, boom(80, 45, .3, .6), 0)
    put(b, boom(80, 45, .3, .75), .45)
    put(b, boom(80, 45, .3, .9), .72)
    return finish(reverb(b, 1.0, .2), .6, .03)


def chord_bells(ms, gap=.06, dur=1.6, amp=.8):
    b = buf(dur + gap * len(ms))
    for i, m in enumerate(ms):
        put(b, bell(hz(m), dur, amp), i * gap)
    return b


def s_r0():
    b = buf(1.3)
    put(b, noise_sweep(.18, 1200, 6000, 'arch', .5), 0)     # 翻面
    put(b, chord_bells([79, 83, 86], .05, 1.0, .7), .1)     # G5 B5 D6
    return finish(reverb(b, 1.2, .25), .6)


def s_r2():
    b = buf(1.8)
    put(b, noise_sweep(.2, 1200, 7000, 'arch', .5), 0)
    put(b, chord_bells([84, 88, 91, 95], .055, 1.2, .75), .1)
    put(b, glitter(.9, 18, 91, 110, .12, 7), .2)
    return finish(reverb(b, 1.5, .3), .7)


def s_r3():
    b = buf(2.4)
    put(b, boom(75, 40, .8, .55), 0)
    put(b, noise_sweep(.25, 2000, 9000, 'down', .35), 0)
    put(b, chord_bells([77, 81, 84, 88, 91], .045, 1.8, .7), .02)   # Fmaj9
    put(b, glitter(1.4, 26, 89, 112, .13, 8), .1)
    return finish(reverb(b, 1.8, .32), .8)


def s_r4():
    b = buf(3.0)
    put(b, boom(70, 36, 1.2, .8), 0)
    put(b, noise_sweep(.5, 3000, 10000, 'down', .3), 0)
    put(b, choir([hz(m) for m in (53, 57, 60, 64)], 2.6, 1.3, .12, 1.2), 0)
    for i, m in enumerate((77, 81, 84, 89, 93, 96)):
        put(b, bell(hz(m), 1.6, .65), .05 + i * .07)
    put(b, glitter(2.0, 40, 91, 112, .13, 9), .2)
    return finish(reverb(b, 2.2, .35), .9)


def s_r5():
    b = buf(3.4)
    put(b, boom(65, 32, 1.6, 1.0), 0)
    put(b, hp(rs.randn(int(2.2 * SR)), 4000) * np.exp(-tt(int(2.2 * SR)) / .5) * .25, 0)   # 镲
    put(b, choir([hz(m) for m in (41, 53, 57, 60, 64, 67)], 3.0, 1.5, .08, 1.4), 0)
    for i, m in enumerate((72, 77, 81, 84, 89, 93, 96, 101)):
        put(b, bell(hz(m), 1.8, .6), .04 + i * .065)
    put(b, glitter(2.4, 60, 89, 115, .14, 10), .15)
    return finish(reverb(b, 2.6, .38), .95)


def s_r6():
    """隐藏款：低沉的一击，暗色和弦慢慢亮起来，金属钟和星屑"""
    b = buf(3.8)
    put(b, boom(55, 26, 2.0, 1.0), 0)
    n = int(3.0 * SR)
    gong = np.zeros(n)
    for r, a, d in ((1, 1, 1.6), (1.48, .6, 1.1), (2.13, .45, .8), (2.71, .3, .6), (3.62, .2, .4)):
        gong += a * np.sin(2 * np.pi * 98 * r * tt(n)) * np.exp(-tt(n) / d)
    put(b, lp(gong, 3000) * .35, 0)
    dark = choir([hz(m) for m in (37, 49, 53, 56, 60, 67)], 3.4, 1.6, .5, 1.4)   # Db maj7#11
    put(b, dark, 0)
    for i, m in enumerate((97, 94, 92, 89, 85, 92, 97, 101, 104)):
        put(b, celesta(hz(m), .9, .35), .35 + i * .09)
    put(b, glitter(2.6, 46, 92, 115, .12, 12), .5)
    return finish(reverb(b, 3.0, .45, 4500), .95)


def s_stamp():
    """蜡封盖下：闷响 + 蜡被压扁的一点点挤压声"""
    b = buf(.6)
    put(b, boom(110, 45, .35, .9), 0)
    m = int(.12 * SR)
    put(b, lp(rs.randn(m), 1400) * np.exp(-tt(m) / .03) * .5, .005)
    put(b, noise_sweep(.15, 900, 400, 'down', .25, .5), .02)
    return finish(reverb(b, .7, .15), .55)


def s_flick():
    b = buf(.16)
    m = int(.05 * SR)
    put(b, bp(rs.randn(m), 2000, 7000) * np.exp(-tt(m) / .008), 0)
    put(b, marimba(hz(96), .1, .15), 0)
    return finish(b, .35, .02)


def s_ticket():
    b = buf(.9)
    put(b, bell(hz(91), .7, .8), 0)
    put(b, bell(hz(96), .8, .7), .05)
    return finish(reverb(b, 1.0, .25), .5)


SFX = {'ok': s_ok, 'bad': s_bad, 'done': s_done, 'open': s_open, 'charge': s_charge, 'r0': s_r0, 'r2': s_r2,
       'r3': s_r3, 'r4': s_r4, 'r5': s_r5, 'r6': s_r6, 'stamp': s_stamp, 'flick': s_flick, 'ticket': s_ticket}


def main():
    wav_dir = sys.argv[sys.argv.index('--wav') + 1] if '--wav' in sys.argv else None
    out = {}
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        for k, fn in SFX.items():
            x = fn()
            w = os.path.join(tmp, k + '.wav')
            wavfile.write(w, SR, (x * 32767).astype(np.int16))
            if wav_dir:
                os.makedirs(wav_dir, exist_ok=True)
                wavfile.write(os.path.join(wav_dir, k + '.wav'), SR, (x * 32767).astype(np.int16))
            m = os.path.join(tmp, k + '.mp3')
            subprocess.check_call(['ffmpeg', '-loglevel', 'error', '-y', '-i', w, '-ac', '1', '-ar', '44100', '-c:a', 'libmp3lame', '-b:a', '96k', m])
            data = open(m, 'rb').read()
            total += len(data)
            out[k] = base64.b64encode(data).decode()
            print('sfx %-7s %.2fs %5d bytes' % (k, len(x) / SR, len(data)))
    js = '/* 音效（MP3，Base64），由 tools/sfx.py 合成生成，app.js 通过 Web Audio / <audio> 播放 */\nwindow.SFX_INLINE={' + \
        ','.join('"%s":"%s"' % (k, v) for k, v in out.items()) + '};\n'
    open(OUT, 'w').write(js)
    print('写入', os.path.relpath(OUT, ROOT), '%d KB' % (len(js) // 1024))


if __name__ == '__main__':
    main()
