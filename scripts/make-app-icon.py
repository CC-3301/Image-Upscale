"""生成 GUI 的 exe / 窗口图标：米白圆角方底 + 深棕几何 IU。

产物（相对仓库根目录，重跑覆盖）：
    gui/assets/app.png   512×512
    gui/assets/app.ico   16/32/48/64/128/256 六档

依赖 Pillow ≥ 8.1.0（ICO 多档写入使用 append_images）。用法：python scripts/make-app-icon.py
"""

import sys
from pathlib import Path

import PIL
from PIL import Image, ImageDraw

BG = (0xEF, 0xE7, 0xDA)      # 米白底
FG = (0x3B, 0x32, 0x2B)      # 深棕字形
SS = 4                       # 超采样倍率（绘制后按块平均降采样）
HEIGHT_RATIO = 0.55          # 字形外接方框高 / 画布边长
CORNER_RATIO = 0.1855        # 圆角半径 / 画布边长
STROKE_RATIO = 0.22          # 笔画厚度 / 字形宽
I_WIDTH_RATIO = 0.215        # I 竖条宽 / 字形宽
GAP_RATIO = 0.10             # I 与 U 间距 / 字形宽
MIN_GAP = 2                  # 最小间距（像素）：16px 下 I 与 U 要留出整列底色
PNG_SIZE = 512
ICO_SIZES = (16, 32, 48, 64, 128, 256)
MIN_PILLOW = (8, 1)          # ICO 多档写入依赖 append_images，低于此版本会被静默忽略
ROOT = Path(__file__).resolve().parent.parent


def layout(size):
    """把画布边长换算成字形各部件尺寸，取整到像素网格"""
    h = round(HEIGHT_RATIO * size)
    x0 = round((size - h) / 2)
    y0 = x0
    bar = max(2, round(STROKE_RATIO * h))
    i_w = max(2, round(I_WIDTH_RATIO * h))
    gap = max(MIN_GAP, round(GAP_RATIO * h))
    return x0, y0, h, bar, i_w, gap


def glyph_mask(size):
    """IU 字形的覆盖掩码（L）：I 圆角竖条 + U 双竖条与底部半圆环"""
    x0, y0, h, bar, i_w, gap = layout(size)
    x1 = x0 + h
    y1 = y0 + h
    ux0 = x0 + i_w + gap
    ux1 = x1
    r_out = (ux1 - ux0) / 2
    cx = ux0 + r_out
    cy = y1 - r_out
    r_in = r_out - bar
    corner = bar / 4

    layer = Image.new("L", (size * SS, size * SS), 0)
    d = ImageDraw.Draw(layer)

    def box(x0_, y0_, x1_, y1_):
        """连续坐标的矩形（右/下边为开区间）→ 像素闭区间，保证整像素对齐"""
        return [x0_ * SS, y0_ * SS, x1_ * SS - 1, y1_ * SS - 1]

    d.rounded_rectangle(box(x0, y0, x0 + i_w, y1), radius=corner * SS, fill=255)
    # U 的两根竖条止于半圆环圆心，与环顶同宽接续
    d.rounded_rectangle(box(ux0, y0, ux0 + bar, cy), radius=corner * SS, fill=255)
    d.rounded_rectangle(box(ux1 - bar, y0, ux1, cy), radius=corner * SS, fill=255)
    d.pieslice(box(cx - r_out, cy - r_out, cx + r_out, cy + r_out), 0, 180, fill=255)
    # 挖空：两竖条之间 + 内半圆
    d.rectangle(box(ux0 + bar, y0, ux1 - bar, cy), fill=0)
    d.pieslice(box(cx - r_in, cy - r_in, cx + r_in, cy + r_in), 0, 180, fill=0)
    return layer.reduce(SS)


def tile_mask(size):
    """圆角方底的覆盖掩码（L）"""
    r = round(CORNER_RATIO * size) * SS
    layer = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(layer).rounded_rectangle(
        [0, 0, size * SS - 1, size * SS - 1], radius=r, fill=255)
    return layer.reduce(SS)


def icon(size):
    """按边长生成一张 RGBA 图标：圆角方底 + 深棕字形

    颜色与 alpha 分开合成：paste 带 mask 时 RGB 也会被乘上 mask（透明画布上是黑），
    半透明边缘因此被压暗，缩到 16px 就是四角黑边。改用 putalpha + alpha_composite。
    """
    tile = Image.new("RGBA", (size, size), BG + (0,))
    tile.putalpha(tile_mask(size))
    glyph = Image.new("RGBA", (size, size), FG + (0,))
    glyph.putalpha(glyph_mask(size))
    return Image.alpha_composite(tile, glyph)


def require_pillow():
    """Pillow 版本过低时退出：旧版忽略 append_images，ICO 各档会退化成 256 缩略图"""
    major, minor = (int(n) for n in PIL.__version__.split(".")[:2])
    if (major, minor) < MIN_PILLOW:
        print(f"错误：需要 Pillow ≥ {MIN_PILLOW[0]}.{MIN_PILLOW[1]}，当前 {PIL.__version__}",
              file=sys.stderr)
        sys.exit(1)


def save_image(img, path, **kwargs):
    """写盘；目录缺失或无写权限时打印路径并以退出码 1 结束"""
    try:
        img.save(path, **kwargs)
    except OSError:
        print(f"无法写入 {path}", file=sys.stderr)
        sys.exit(1)


def main():
    require_pillow()
    png = ROOT / "gui" / "assets" / "app.png"
    ico = ROOT / "gui" / "assets" / "app.ico"
    save_image(icon(PNG_SIZE), png)

    frames = [icon(s) for s in ICO_SIZES]
    largest = frames[-1]
    save_image(largest, ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES],
               append_images=frames[:-1])
    print(f"saved {png.relative_to(ROOT)} ({PNG_SIZE}x{PNG_SIZE})")
    print(f"saved {ico.relative_to(ROOT)} ({'/'.join(str(s) for s in ICO_SIZES)})")


if __name__ == "__main__":
    main()
