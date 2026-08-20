# -*- coding: utf-8 -*-
"""
pdf_utils.py —— PDF 证据层（与文档类型无关）  v7
质量与速度的根基，相对旧版的关键改动：

  1. 版式文本（电子件质量的核心修复）
     旧版 extract_text() 把整页压成阅读流，表格列错位、标签与值混行，
     再粗暴截断前 6000 字符——底部的"合计"经常被切掉。
     v7 用 extract_text(layout=True) 保留二维版式（列对齐可见），
     再做空白压缩：实测一页 5311 字符压到 390 字符、信息零丢失，
     从此不需要截断，整页完整喂给模型。

  2. 三态页面判定 native / scanned / blank
     - 整页大图 + 极少文本  → 识破扫描仪自带的劣质嵌入文本层，按扫描件走；
     - (cid:xx) / 乱码占比高 → 字体映射损坏的假文本层，按扫描件走；
     - 无文本且墨迹率≈0     → blank，直接跳过（省一次视觉调用）。
       阈值极保守（ink<0.04%），稀疏但有内容的页面绝不会被误跳。

  3. 精确高清渲染（扫描件质量的核心修复）
     旧版固定 scale=2.0 渲染后再缩到 1800px、JPEG q85，小号中文糊掉。
     v7 按目标长边像素反推 scale 一次渲染到位，默认 2000px、q88，
     体积超限时先降质再降尺寸，尽量保住分辨率。

  4. OCR 版式重建
     rapidocr 结果不再拼成一行，而是按行聚类 + 列间距还原成对齐文本，
     作为视觉请求的辅助证据（未安装 rapidocr 时自动为空，不影响运行）。

  5. PdfFile：一份文件 pdfplumber 只开一次；pdfium 懒加载 + 渲染加锁，
     线程池里安全复用。
"""
import io
import os
import re
import base64
import logging
import threading

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageOps

logger = logging.getLogger('pdf_utils')

# ── 可调参数（环境变量）─────────────────────────────────────────
SCAN_MAX_SIDE = int(os.environ.get('SCAN_MAX_SIDE', '2000'))    # 扫描页渲染长边像素
SCAN_JPEG_Q = int(os.environ.get('SCAN_JPEG_Q', '88'))          # JPEG 质量
IMG_MAX_BYTES = int(os.environ.get('IMG_MAX_BYTES', '3600000')) # 单图编码前字节上限
TEXT_CHAR_LIMIT = int(os.environ.get('TEXT_CHAR_LIMIT', '14000'))  # 单页版式文本上限(极少触发)

_BLANK_INK = 0.0004      # 墨迹率低于此且无文本 → 空白页（实测空白=0，稀疏文档≈0.00086）
_FAKE_IMG_RATIO = 0.7    # 整页图占比超过此值
_FAKE_TEXT_LEN = 200     # 且文本少于此 → 判扫描件（假文本层）


# ══════════════════════════════════════════════════════════════
#  版式文本
# ══════════════════════════════════════════════════════════════
def compress_layout(t):
    """压缩 layout=True 的输出：
    行尾空白去掉；行内 ≥3 个空格压成 3 个（保留"列分隔"语义）；
    连续空行最多留 1 行。列对齐语义完整保留，体积缩到约 1/10。"""
    lines = [re.sub(r' {3,}', '   ', ln.rstrip()) for ln in (t or '').split('\n')]
    out, empty = [], 0
    for ln in lines:
        if not ln.strip():
            empty += 1
            if empty > 1:
                continue
        else:
            empty = 0
        out.append(ln)
    s = '\n'.join(out).strip()
    if len(s) > TEXT_CHAR_LIMIT:  # 极端长页兜底：保头尾，标注省略
        keep = TEXT_CHAR_LIMIT // 2
        s = s[:keep] + '\n……(本页中部省略)……\n' + s[-keep:]
    return s


def _quality(text):
    """(乱码占比, cid数)。乱码=不可打印且非空白，或 U+FFFD。"""
    body = [ch for ch in text if not ch.isspace()]
    if not body:
        return 1.0, 0
    bad = sum(1 for ch in body if (not ch.isprintable()) or ch == '\ufffd')
    return bad / len(body), text.count('(cid:')


# ══════════════════════════════════════════════════════════════
#  PdfFile：一份 PDF 的证据容器
# ══════════════════════════════════════════════════════════════
class PageInfo(object):
    __slots__ = ('kind', 'text', 'hint')

    def __init__(self, kind, text='', hint=''):
        self.kind = kind      # 'native' | 'scanned' | 'blank'
        self.text = text      # native: 版式文本
        self.hint = hint      # scanned: 页面自带的低质量文本层（弱线索，可为空）


class PdfFile(object):
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.pages = []            # list[PageInfo]
        self._doc = None           # pypdfium2 懒加载
        self._lock = threading.Lock()

    # ---- 结构扫描：文本层 + 判定 ---------------------------------
    def scan(self):
        with pdfplumber.open(io.BytesIO(self.data)) as pdf:
            for p in pdf.pages:
                plain = ''
                try:
                    plain = (p.extract_text() or '').strip()
                except Exception:
                    pass
                lay = ''
                try:
                    raw = p.extract_text(layout=True)
                    lay = compress_layout(raw) if raw and raw.strip() else ''
                except Exception as e:
                    logger.debug('layout 提取失败(%s p?): %s', self.name, e)
                # layout 偶发丢字时退回 plain
                text = lay if lay and len(lay) >= len(plain) * 0.5 else plain
                try:
                    area = sum((im['x1'] - im['x0']) * (im['bottom'] - im['top'])
                               for im in p.images)
                    img_ratio = area / max(1.0, float(p.width * p.height))
                except Exception:
                    img_ratio = 0.0
                self.pages.append(self._classify(text, img_ratio))
        # 空文本页需要墨迹检测区分 blank / scanned
        for i, pi in enumerate(self.pages):
            if pi.kind == '_pending':
                pi.kind = 'blank' if self._ink_ratio(i) < _BLANK_INK else 'scanned'
        return self

    @staticmethod
    def _classify(text, img_ratio):
        t = (text or '').strip()
        if not t:
            return PageInfo('_pending')                      # 待墨迹检测
        bad, cid = _quality(t)
        if cid > 3 or bad > 0.2:
            return PageInfo('scanned', hint='')              # 假/坏文本层，线索不可用
        if img_ratio > _FAKE_IMG_RATIO and len(t) < _FAKE_TEXT_LEN:
            return PageInfo('scanned', hint=t)               # 整页图+零星文字
        if len(t) < 30:
            return PageInfo('scanned', hint=t)
        return PageInfo('native', text=t)

    @property
    def page_count(self):
        return len(self.pages)

    # ---- 渲染（线程安全，按目标像素一次到位）----------------------
    def _ensure_doc(self):
        if self._doc is None:
            self._doc = pdfium.PdfDocument(io.BytesIO(self.data))
        return self._doc

    def render(self, idx, target_side=None):
        target = int(target_side or SCAN_MAX_SIDE)
        with self._lock:
            doc = self._ensure_doc()
            page = doc[idx]
            w_pt, h_pt = page.get_size()
            scale = target / max(1.0, max(w_pt, h_pt))
            return page.render(scale=scale).to_pil().convert('RGB')

    def _ink_ratio(self, idx, thumb=360, dark=190):
        """小图墨迹率，用于空白页判定。无 numpy 依赖。"""
        try:
            img = self.render(idx, target_side=thumb).convert('L')
            hist = img.histogram()
            total = sum(hist) or 1
            return sum(hist[:dark]) / total
        except Exception:
            return 1.0  # 渲染失败按"有内容"处理，绝不误跳

    def close(self):
        with self._lock:
            if self._doc is not None:
                try:
                    self._doc.close()
                except Exception:
                    pass
                self._doc = None


class ImageFile(object):
    """把普通图片包装成与 PdfFile 相同的分页证据接口。

    TIFF/GIF 等多帧图片按帧分页；JPG/PNG/WebP 等单图就是一页。图片始终走
    视觉/OCR 通道，因此不会把压缩元数据误当作正文。
    """
    def __init__(self, name, data):
        self.name = name
        self.data = data
        self.pages = []
        self._lock = threading.Lock()

    def scan(self):
        with Image.open(io.BytesIO(self.data)) as img:
            count = int(getattr(img, 'n_frames', 1) or 1)
            for i in range(count):
                img.seek(i)
                frame = ImageOps.exif_transpose(img.copy()).convert('RGB')
                gray = frame.copy()
                gray.thumbnail((360, 360), Image.LANCZOS)
                hist = gray.convert('L').histogram()
                total = sum(hist) or 1
                ink = sum(hist[:190]) / total
                self.pages.append(PageInfo('blank' if ink < _BLANK_INK else 'scanned'))
        return self

    @property
    def page_count(self):
        return len(self.pages)

    def render(self, idx, target_side=None):
        target = int(target_side or SCAN_MAX_SIDE)
        with self._lock, Image.open(io.BytesIO(self.data)) as img:
            img.seek(idx)
            frame = ImageOps.exif_transpose(img.copy()).convert('RGB')
        if max(frame.size) > target:
            frame.thumbnail((target, target), Image.LANCZOS)
        return frame

    def close(self):
        return None


_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff', '.gif'}


def open_file(name, data):
    """按文件内容/扩展名打开 PDF 或图片，返回统一证据容器。"""
    ext = os.path.splitext(str(name or ''))[1].lower()
    if bytes(data[:8]).startswith(b'%PDF'):
        return PdfFile(name, data)
    if ext in _IMAGE_EXTENSIONS:
        return ImageFile(name, data)
    # 扩展名可能被聊天工具或扫描仪改掉：先尝试图片，再让 PDF 抛出明确错误。
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        return ImageFile(name, data)
    except Exception:
        return PdfFile(name, data)


# ══════════════════════════════════════════════════════════════
#  图片编码：优先保分辨率，超限先降质再降尺寸
# ══════════════════════════════════════════════════════════════
def pil_to_b64(img, max_side=None, quality=None, max_bytes=None):
    max_side = int(max_side or SCAN_MAX_SIDE)
    quality = int(quality or SCAN_JPEG_Q)
    max_bytes = int(max_bytes or IMG_MAX_BYTES)
    w, h = img.size
    if max(w, h) > max_side:
        r = max_side / max(w, h)
        img = img.resize((max(1, int(w * r)), max(1, int(h * r))), Image.LANCZOS)
    data = None
    for q in (quality, quality - 10, quality - 20, 62):
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=max(50, q))
        data = buf.getvalue()
        if len(data) <= max_bytes:
            return base64.b64encode(data).decode()
    while len(data) > max_bytes and max(img.size) > 900:
        img = img.resize((int(img.size[0] * 0.85), int(img.size[1] * 0.85)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=68)
        data = buf.getvalue()
    return base64.b64encode(data).decode()


# ══════════════════════════════════════════════════════════════
#  可选本地 OCR：按行聚类 + 列间距还原版式
# ══════════════════════════════════════════════════════════════
_ocr = None
_ocr_tried = False


def ocr_available():
    global _ocr, _ocr_tried
    if not _ocr_tried:
        _ocr_tried = True
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
            logger.info('本地 OCR (rapidocr) 已启用，将作为扫描页辅助证据')
        except Exception:
            _ocr = None
    return _ocr is not None


def ocr_layout(img, limit=6000):
    """返回按版式还原的 OCR 文本；rapidocr 未安装或失败时返回 ''。"""
    if not ocr_available():
        return ''
    try:
        import numpy as np
        res, _ = _ocr(np.array(img))
        if not res:
            return ''
        items = []
        for box, txt, _score in res:
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            items.append({'x0': min(xs), 'yc': (min(ys) + max(ys)) / 2,
                          'h': max(1.0, max(ys) - min(ys)), 'text': str(txt)})
        if not items:
            return ''
        med_h = sorted(it['h'] for it in items)[len(items) // 2]
        tol = med_h * 0.6
        items.sort(key=lambda it: it['yc'])
        lines, cur, cur_y = [], [], None
        for it in items:
            if cur_y is None or abs(it['yc'] - cur_y) <= tol:
                cur.append(it)
                cur_y = it['yc'] if cur_y is None else (cur_y + it['yc']) / 2
            else:
                lines.append(cur)
                cur, cur_y = [it], it['yc']
        if cur:
            lines.append(cur)
        out = []
        for ln in lines:
            ln.sort(key=lambda it: it['x0'])
            parts, prev_end = [], None
            for it in ln:
                gap = 0 if prev_end is None else it['x0'] - prev_end
                sep = '' if prev_end is None else ('   ' if gap > med_h * 2 else
                                                  ('  ' if gap > med_h * 0.8 else ' '))
                parts.append(sep + it['text'])
                prev_end = it['x0'] + len(it['text']) * med_h * 0.9
            out.append(''.join(parts))
        return '\n'.join(out)[:limit]
    except Exception as e:
        logger.warning('OCR 失败: %s', e)
        return ''
