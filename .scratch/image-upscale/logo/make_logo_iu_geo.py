# -*- coding: utf-8 -*-
"""工单 32（三轮方向稿）：几何 IU —— 字形本身铺满画布，字母即 Logo（等维护者确认）

iu-geo-tile.png/.ico   靛紫渐变圆角方底 + 白色几何 IU 满铺（边距约 8%）
iu-geo-bare.png/.ico   透明底 + 渐变填充几何 IU（wordmark，字母外无色块）

U 的构造：双竖条 + 底部半圆环（外半圆填 255、内半圆挖 0），与竖条相切衔接。
"""
from PIL import Image, ImageDraw

SIZE = 1024
PAD = 82          # 满铺边距
BAR = 190         # 笔画厚度（I 与 U 一致）
I_W = 185         # I 竖条宽
GAP = 85          # I 与 U 间距

INDIGO = (99, 102, 241)
VIOLET = (139, 92, 246)


def v_gradient(c1, c2, w=SIZE, h=SIZE):
    img = Image.new("RGB", (w, h))
    for y in range(h):
        t = y / (h - 1)
        img.paste(tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)), (0, y, w, y + 1))
    return img


def rounded_tile():
    img = v_gradient(INDIGO, VIOLET).convert("RGBA")
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=190, fill=255)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def draw_iu(target: Image.Image, fill_img: Image.Image, x0, y0, x1, y1):
    """在 target 上以 fill_img 填充绘制几何 IU；笔画厚度随内容宽度等比缩放"""
    content = x1 - x0
    bar = int(content * 0.22)
    i_w = int(content * 0.215)
    gap = int(content * 0.10)
    r = bar // 4  # 顶部圆角
    layer = Image.new("L", (SIZE, SIZE), 0)
    d = ImageDraw.Draw(layer)

    # I：圆角竖条
    d.rounded_rectangle([x0, y0, x0 + i_w, y1], radius=r, fill=255)

    # U：左竖条 + 右竖条 + 底部半圆环
    ux0 = x0 + i_w + gap
    ux1 = x1
    cx = (ux0 + ux1) // 2
    r_outer = (ux1 - ux0) // 2
    cy = y1 - r_outer              # 半圆心（底部半圆的上沿）
    r_in = r_outer - bar

    d.rounded_rectangle([ux0, y0, ux0 + bar, cy + 60], radius=r, fill=255)   # 左竖条（下延入环区防接缝）
    d.rounded_rectangle([ux1 - bar, y0, ux1, cy + 60], radius=r, fill=255)   # 右竖条
    d.pieslice([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer], 0, 180, fill=255)
    # 内挖空
    d.rectangle([ux0 + bar, y0, ux1 - bar, cy + 2], fill=0)
    if r_in > 0:
        d.pieslice([cx - r_in, cy - r_in, cx + r_in, cy + r_in], 0, 180, fill=0)

    target.alpha_composite(Image.composite(fill_img, Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)), layer))


def save_all(img, name):
    img.resize((512, 512), Image.LANCZOS).save(f"{name}.png")
    img.resize((256, 256), Image.LANCZOS).save(
        f"{name}.ico", format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("saved", name)


# C1 变体：渐变圆角方底 + 白色几何 IU（pad 可调，验证轮三档）
def geo_tile(pad=PAD, name="iu-geo-tile"):
    img = rounded_tile()
    white = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255))
    draw_iu(img, white, pad, pad, SIZE - pad, SIZE - pad)
    save_all(img, name)


# C2：透明底 + 靛紫渐变填充几何 IU（wordmark）
def geo_bare():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad = v_gradient(INDIGO, VIOLET).convert("RGBA")
    draw_iu(img, grad, PAD, PAD, SIZE - PAD, SIZE - PAD)
    save_all(img, "iu-geo-bare")


if __name__ == "__main__":
    geo_tile()
    geo_bare()
    geo_tile(112, "iu-geo-tile-pad112")   # 留白三档（验证轮）
    geo_tile(136, "iu-geo-tile-pad136")
    geo_tile(160, "iu-geo-tile-pad160")
