#!/usr/bin/env python3
"""单词发音 + 例句朗读：开源 TTS（Kokoro-82M，Apache-2.0，可商用）离线生成，声线 bm_fable（英式温柔男声）。

用法：python3 tools/tts.py [--ids 1,2,3] [--pack-only]
  首次运行会下载模型到 tools/.tts/（约 350MB，不进仓库），单段合成结果缓存在 tools/.tts/clips/
  输出：src/audio/w/<组>.m4a（单词）、src/audio/s/<组>.m4a（例句），每组 20 段；索引 src/js/voice-map.js
依赖：pip install kokoro-onnx soundfile scipy；ffmpeg
处理：去掉首尾静音 → 柔和混响（梦幻一点，但不糊）→ 响度统一 → 按组拼接 → AAC 单声道 16kHz
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request

import numpy as np
import soundfile as sf
from scipy import signal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'tools', '.tts')
OUT = os.path.join(ROOT, 'src', 'audio')
MODEL_URL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'
VOICE = 'bm_fable'
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import sfx as FX  # noqa: E402  复用混响/滤波


def model():
    os.makedirs(CACHE, exist_ok=True)
    for f in ('kokoro-v1.0.onnx', 'voices-v1.0.bin'):
        p = os.path.join(CACHE, f)
        if not os.path.exists(p):
            print('下载', f)
            urllib.request.urlretrieve(MODEL_URL + f, p)
    from kokoro_onnx import Kokoro
    return Kokoro(os.path.join(CACHE, 'kokoro-v1.0.onnx'), os.path.join(CACHE, 'voices-v1.0.bin'))


def words():
    js = open(os.path.join(ROOT, 'src', 'js', 'data.js'), encoding='utf-8').read()
    return json.loads(js[js.index('=[') + 1:js.rindex(']') + 1])


def say_text(s):
    s = s.replace('…', '...').replace('—', ', ').replace('–', ', ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def trim(x, sr, thr=.012, pad=.04):
    idx = np.where(np.abs(x) > thr)[0]
    if not len(idx):
        return x
    a, b = max(0, idx[0] - int(pad * sr)), min(len(x), idx[-1] + int(pad * sr))
    return x[a:b]


def dreamy(x, sr, wet, tail):
    """柔和混响（梦幻一点，但不糊），尾音留 tail 秒。低码率下不再额外提亮高频，省下的码率给人声"""
    up = signal.resample_poly(x, 441, 240)          # 24k → 44.1k，复用 sfx.py 的滤波器
    up = FX.hp(up, 80)
    up = np.concatenate([up, np.zeros(int(tail * 44100))])
    y = FX.reverb(up, 1.6, wet, 6000, .02)
    n = int(.04 * 44100)
    y[-n:] *= np.linspace(1, 0, n)
    rms = np.sqrt(np.mean(y[np.abs(y) > .02 * np.max(np.abs(y))] ** 2))
    y = y * (.16 / (rms + 1e-9))                     # 响度统一
    return np.clip(y, -.95, .95)


# 每组 20 词打成一个音频（省去上千个小文件的容器开销），VOICE_MAP 记录每段的起点和时长
GROUP, GAP = 20, .45
KINDS = {'w': dict(speed=.82, wet=.14, tail=.22, br='18k', cut='7000'),
         's': dict(speed=.92, wet=.2, tail=.3, br='14k', cut='6500')}


def clip_path(kind, i):
    return os.path.join(CACHE, 'clips', kind, '%d.wav' % i)


def synth(k, W, ids, only):
    n = 0
    for r in W:
        i = r[0]
        if ids and i not in ids:
            continue
        for kind, cfg in KINDS.items():
            if only and kind != only:
                continue
            p = clip_path(kind, i)
            if os.path.exists(p) and not ids:
                continue
            text = r[2] + '.' if kind == 'w' else say_text(r[9])
            x, sr = k.create(text, voice=VOICE, speed=cfg['speed'], lang='en-gb')
            y = dreamy(trim(x, sr), sr, cfg['wet'], cfg['tail'])
            os.makedirs(os.path.dirname(p), exist_ok=True)
            sf.write(p, y.astype(np.float32), 44100, subtype='FLOAT')
        n += 1
        if n % 50 == 0:
            print('合成', n, flush=True)


def pack(W):
    vmap = {}
    total = 0
    for kind, cfg in KINDS.items():
        segs = []
        for g in range(0, len(W), GROUP):
            parts, t = [], 0.0
            for r in W[g:g + GROUP]:
                y, _ = sf.read(clip_path(kind, r[0]))
                parts += [np.zeros(int(GAP * 44100)), y]
                t += GAP
                segs.append([round(t, 3), round(len(y) / 44100, 3)])
                t += len(y) / 44100
            parts.append(np.zeros(int(GAP * 44100)))
            out = os.path.join(OUT, kind, '%02d.m4a' % (g // GROUP + 1))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with tempfile.NamedTemporaryFile(suffix='.wav') as tmp:
                sf.write(tmp.name, np.concatenate(parts), 44100)
                subprocess.check_call(['ffmpeg', '-loglevel', 'error', '-y', '-i', tmp.name, '-ac', '1', '-ar', '16000', '-c:a', 'aac',
                                       '-b:a', cfg['br'], '-cutoff', cfg['cut'], '-movflags', '+faststart', out])
            total += os.path.getsize(out)
        vmap[kind] = segs
        print(kind, '%.2f MB' % (sum(os.path.getsize(os.path.join(OUT, kind, f)) for f in os.listdir(os.path.join(OUT, kind))) / 1e6))
    with open(os.path.join(ROOT, 'src', 'js', 'voice-map.js'), 'w', encoding='utf-8') as f:
        f.write('/* 发音与例句音频索引，由 tools/tts.py 生成。audio/<w|s>/<组>.m4a 里每段的 [起点秒, 时长秒]，按词序排列 */\n'
                'window.VOICE_MAP={g:%d,w:%s,s:%s};\n' % (GROUP, json.dumps(vmap['w'], separators=(',', ':')), json.dumps(vmap['s'], separators=(',', ':'))))
    print('合计 %.2f MB' % (total / 1e6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', choices=['w', 's'])
    ap.add_argument('--ids', help='只重新合成这些序号（逗号分隔）')
    ap.add_argument('--pack-only', action='store_true', help='不合成，只用缓存重新打包')
    a = ap.parse_args()
    W = words()
    if not a.pack_only:
        synth(model(), W, set(int(x) for x in a.ids.split(',')) if a.ids else None, a.only)
    pack(W)


if __name__ == '__main__':
    main()
