# -*- coding: utf-8 -*-
"""工单 32：LOGO 三版提案（程序化绘制，可复现）

产出（同目录）：proposal-1-magnifier.png / proposal-2-pixels.png / proposal-3-layers.png
每版同时输出 256px PNG 与多尺寸 .ico（256/128/64/48/32/16）。

设计原则：粗轮廓 + 高对比，16px 下仍可辨识；主色与 GUI 无关（未定主题色，先出方向）。
"""
from PIL import Image, ImageDraw

SIZE = 1024  # 超采样画布，最后 LANCZOS 缩到 512/256


def canvas_gradient(c1, c2):
    """垂直渐变底图"""
    img = Image.new("RGB", (SIZE, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        img.paste(tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)), (0, y, SIZE, y + 1))
    return img


def rounded_bg(c1, c2, radius=180):
    """渐变 + 圆角方形蒙版，返回 RGBA"""
    img = canvas_gradient(c1, c2).convert("RGBA")
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=255)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def save_all(img, name):
    p512 = img.resize((512, 512), Image.LANCZOS)
    p512.save(f"{name}.png")
    p256 = img.resize((256, 256), Image.LANCZOS)
    p256.save(f"{name}.ico", format="ICO",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("saved", name)


# ---------- 方案 1：放大镜 + 上行箭头（直白表达"放大"） ----------
def proposal_1():
    img = rounded_bg((99, 102, 241), (139, 92, 246))  # indigo → violet
    d = ImageDraw.Draw(img)
    w = 72  # 笔画宽
    # 镜体（圆环）
    cx, cy, r = 460, 440, 270
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 255), width=w)
    # 镜内上箭头（放大意象）
    ax, ay = cx, cy + 40
    d.polygon([(ax - 110, ay + 60), (ax, ay - 90), (ax + 110, ay + 60)], fill=(255, 255, 255, 255))
    d.rectangle([ax - 36, ay + 10, ax + 36, ay + 150], fill=(255, 255, 255, 255))
    # 镜柄（右下 45°）
    import math
    hx, hy = cx + r * math.cos(math.radians(45)), cy + r * math.sin(math.radians(45))
    L = 210
    ex, ey = hx + L * math.cos(math.radians(45)), hy + L * math.sin(math.radians(45))
    d.line([(hx, hy), (ex, ey)], fill=(255, 255, 255, 255), width=int(w * 1.2))
    d.ellipse([ex - w * 0.6, ey - w * 0.6, ex + w * 0.6, ey + w * 0.6], fill=(255, 255, 255, 255))
    save_all(img, "proposal-1-magnifier")


# ---------- 方案 2：像素阶梯（分辨率层级攀升，深底亮色） ----------
def proposal_2():
    img = rounded_bg((15, 23, 42), (30, 41, 59))  # 深海军蓝
    d = ImageDraw.Draw(img)
    # 四个沿对角线递增的圆角方块：小 → 大（左下 → 右上）
    specs = [  # (中心x, 中心y, 边长, 颜色)
        (290, 790, 110, (34, 211, 238)),    # cyan
        (460, 620, 180, (45, 212, 191)),    # teal
        (660, 420, 240, (52, 211, 153)),    # emerald
    ]
    for x, y, s, c in specs:
        d.rounded_rectangle([x - s // 2, y - s // 2, x + s // 2, y + s // 2],
                            radius=s // 6, fill=c + (255,))
    # 顶端上箭头：攀升意象（与方块留白，不重叠）
    ax, ay = 845, 145
    d.polygon([(ax - 95, ay + 55), (ax, ay - 80), (ax + 95, ay + 55)], fill=(52, 211, 153, 255))
    d.rectangle([ax - 32, ay, ax + 32, ay + 110], fill=(52, 211, 153, 255))
    save_all(img, "proposal-2-pixels")


# ---------- 方案 3：层叠图像 + 升箭头（图像处理语义，暖色） ----------
def proposal_3():
    img = rounded_bg((28, 25, 23), (41, 37, 36))  # 深炭色
    d = ImageDraw.Draw(img)
    # 三张错位堆叠的"照片"卡片（由后到前，亮度递增）
    cards = [
        (190, 640, 560, 400, (120, 113, 108)),
        (250, 560, 560, 400, (202, 138, 4)),
        (310, 480, 560, 400, (245, 158, 11)),  # amber
    ]
    for x, y, w2, h2, c in cards:
        d.rounded_rectangle([x, y, x + w2, y + h2], radius=36, fill=c + (255,))
    # 顶卡片内的“山与日”抽象图（图像语义；太阳高于山脊线）
    d.ellipse([650, 525, 745, 620], fill=(254, 243, 199, 255))
    d.polygon([(350, 800), (520, 590), (640, 720), (720, 640), (830, 800)], fill=(254, 243, 199, 255))
    # 右上上箭头
    ax, ay = 840, 150
    d.polygon([(ax - 100, ay + 55), (ax, ay - 80), (ax + 100, ay + 55)], fill=(245, 158, 11, 255))
    d.rectangle([ax - 34, ay, ax + 34, ay + 115], fill=(245, 158, 11, 255))
    save_all(img, "proposal-3-layers")


if __name__ == "__main__":
    proposal_1()
    proposal_2()
    proposal_3()
