#!/usr/bin/env python3
"""蜡封抠图：白底照片 → 透明底 webp（统一正圆、统一尺寸与留白）

用法：python3 tools/seals.py            # 处理 seals-src/*.jpg|png → src/img/seal/<同名>.webp
依赖：pip install opencv-python-headless scipy scikit-image pillow numpy

步骤：
1. 分割：彩色蜡按饱和度分割（白底、灰色投影几乎无色，会被干净去掉）；
   白蜡与白底颜色太近，改用 GrabCut + 测地线主动轮廓收掉投影；都只保留最大块，去掉水印和碎片
2. 三分图 + alpha matting：彩色蜡在边缘带按饱和度估计透明度，边缘颜色取相邻蜡色
   （去色污染），消除白边；白蜡用平滑后的分割边界
3. 椭圆拟合 + 仿射校正：斜着拍的蜡封是椭圆，按长短轴把它拉回正圆
4. 统一裁切、留白、尺寸
"""
import glob
import os

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'seals-src')
OUT = os.path.join(ROOT, 'src', 'img', 'seal')
SIZE = 360      # 输出边长
MARGIN = .04    # 四周留白
WORK = 1024     # 处理分辨率


def largest(mask):
    lab, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(mask, lab, range(1, n + 1))
        mask = lab == (np.argmax(sizes) + 1)
    return ndimage.binary_fill_holes(mask)


def segment(rgb):
    """返回 (前景掩码, 是否彩色蜡)。彩色蜡按饱和度分割；白蜡用 GrabCut"""
    h, w = rgb.shape[:2]
    sat = rgb.max(2) - rgb.min(2)
    yy, xx = np.mgrid[0:h, 0:w]
    center = (xx - w / 2) ** 2 + (yy - h / 2) ** 2 < (min(h, w) * .25) ** 2
    s_seal = np.median(sat[center])
    if s_seal > 25:
        # 白底、灰色投影饱和度都很低；阈值取蜡面饱和度的三分之一
        fg = sat > max(14, s_seal * .33)
        fg = ndimage.binary_closing(fg, structure=np.ones((3, 3)), iterations=4)
        fg = largest(fg)
        fg = ndimage.binary_opening(fg, iterations=3)
        return largest(fg), True, s_seal
    bgr = np.ascontiguousarray(rgb[:, :, ::-1].astype(np.uint8))
    mask = np.zeros((h, w), np.uint8)
    rect = (int(w * .03), int(h * .03), int(w * .94), int(h * .94))
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, mask, rect, bgd, fgd, 6, cv2.GC_INIT_WITH_RECT)
    fg = largest((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD))
    # 白蜡与投影颜色接近，只能靠边缘区分：测地线主动轮廓从 GrabCut 结果向内收缩，
    # 碰到蜡沿的明暗交界就停下，平缓的灰色投影会被收掉；再闭运算补小缺口、平滑轮廓
    from skimage.segmentation import inverse_gaussian_gradient, morphological_geodesic_active_contour
    g = inverse_gaussian_gradient(rgb.mean(2) / 255, alpha=400, sigma=2)
    fg = morphological_geodesic_active_contour(g, num_iter=120, init_level_set=fg.astype(np.int8), smoothing=2, balloon=-1, threshold=.5).astype(bool)
    fg = largest(ndimage.binary_closing(largest(fg), iterations=8))
    fg = cv2.GaussianBlur(fg.astype(np.float32), (0, 0), 3) > .5
    return largest(fg), False, s_seal


def matte(img, fg, colored, s_seal):
    """三分图 alpha matting + 去色污染。img 为 RGB float32"""
    sure_fg = ndimage.binary_erosion(fg, iterations=5)
    sure_bg = ~ndimage.binary_dilation(fg, iterations=4)
    unknown = ~sure_fg & ~sure_bg
    _, idx = ndimage.distance_transform_edt(~sure_fg, return_indices=True)
    F = img[idx[0], idx[1]]                                  # 最近的蜡面颜色
    a_shape = cv2.GaussianBlur(fg.astype(np.float32), (0, 0), 1.4)
    if colored:
        # 饱和度 → 透明度：白底、灰投影都按「无色」处理，边缘颜色直接用相邻的蜡色（等于去色污染）
        sat = img.max(2) - img.min(2)
        satF = np.maximum(F.max(2) - F.min(2), 1)
        a_sat = np.clip((sat - 10) / np.maximum(satF - 10, 8), 0, 1)
        a_edge = np.minimum(a_sat, np.clip(a_shape * 1.5, 0, 1))
        col = F
    else:
        a_edge = a_shape                                      # 白蜡与白底颜色太近，只用形状
        col = img * .4 + F * .6
    alpha = np.where(sure_fg, 1.0, np.where(sure_bg, 0.0, a_edge)).astype(np.float32)
    alpha = cv2.GaussianBlur(alpha, (0, 0), .6)
    alpha[sure_fg] = 1
    out = np.where(unknown[..., None], col, img)
    return out.astype(np.float32), alpha


def roundify(rgb, alpha):
    """椭圆拟合，把斜拍成椭圆的蜡封拉回正圆"""
    m = (alpha > .5).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cnts, key=cv2.contourArea)
    (cx, cy), (ax1, ax2), ang = cv2.fitEllipse(c)
    long_, short = max(ax1, ax2), min(ax1, ax2)
    ratio = short / long_
    if ratio > .985:
        return rgb, alpha, ratio
    theta = np.deg2rad(ang if ax1 < ax2 else ang + 90)      # fitEllipse 的角度对应 ax1
    u = np.array([np.cos(theta), np.sin(theta)])
    A = np.eye(2) + (long_ / short - 1) * np.outer(u, u)     # 只沿短轴方向放大
    h, w = alpha.shape
    pad = int(max(h, w) * .25)
    ctr = np.array([cx + pad, cy + pad])
    M = np.hstack([A, (ctr - A @ ctr)[:, None]]).astype(np.float32)
    big = lambda x: cv2.copyMakeBorder(x, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    size = (w + 2 * pad, h + 2 * pad)
    rgb2 = cv2.warpAffine(big(rgb), M, size, flags=cv2.INTER_CUBIC)
    a2 = cv2.warpAffine(big(alpha), M, size, flags=cv2.INTER_CUBIC)
    return rgb2, np.clip(a2, 0, 1), ratio


def process(path):
    im = Image.open(path).convert('RGB')
    k = WORK / max(im.size)
    im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
    rgb = np.asarray(im).astype(np.float32)
    fg, colored, s_seal = segment(rgb)
    rgb, alpha = matte(rgb, fg, colored, s_seal)
    rgb, alpha, ratio = roundify(rgb, alpha)
    ys, xs = np.nonzero(alpha > .02)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    rgba = np.dstack([rgb, alpha * 255]).clip(0, 255).astype(np.uint8)[y0:y1 + 1, x0:x1 + 1]
    tile = Image.fromarray(rgba, 'RGBA')
    side = int(max(tile.size) / (1 - 2 * MARGIN))
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    canvas.paste(tile, ((side - tile.width) // 2, (side - tile.height) // 2))
    return canvas.resize((SIZE, SIZE), Image.LANCZOS), ratio


def main():
    os.makedirs(OUT, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(SRC, '*.jpg')) + glob.glob(os.path.join(SRC, '*.png'))):
        name = os.path.splitext(os.path.basename(p))[0]
        out = os.path.join(OUT, name + '.webp')
        img, ratio = process(p)
        img.save(out, 'WEBP', quality=90, method=6)
        print('seal %-9s 短长轴比 %.3f%s  %d bytes' % (name, ratio, ' → 已校正为正圆' if ratio <= .985 else '', os.path.getsize(out)))


if __name__ == '__main__':
    main()
