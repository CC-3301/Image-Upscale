# -*- coding: utf-8 -*-
"""工单 32（定稿轮）：IU 字母标识三版（维护者定调：直接用 IU 当主题）

产出：iu-v1-flat.png/.ico   白字 IU · 靛紫渐变圆角方（扁平，最常规）
      iu-v2-glow.png/.ico   渐变字 IU · 深海军蓝底（青→翠）
      iu-v3-light.png/.ico  浅底 + 渐变字 IU · 靛紫（亮色调）
"""
from PIL import Image, ImageDraw, ImageFont

SIZE = 1024
FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"
FONT_DIN = "C:/Windows/Fonts/bahnschrift.ttf"


def v_gradient(c1, c2, w=SIZE, h=SIZE):
    img = Image.new("RGB", (w, h))
    for y in range(h):
        t = y / (h - 1)
        img.paste(tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)), (0, y, w, y + 1))
    return img


def rounded_bg(c1, c2, radius=190):
    img = v_gradient(c1, c2).convert("RGBA")
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


def fit_font_size(text, font_path, target_w, stroke=0):
    """按目标宽度反推字号（验证轮：IU 字母放大）"""
    probe = ImageFont.truetype(font_path, 100)
    ld = ImageDraw.Draw(Image.new("L", (8, 8)))
    b = ld.textbbox((0, 0), text, font=probe, stroke_width=stroke)
    return int(100 * target_w / (b[2] - b[0]))


def draw_text_center(img, text, font_path, font_size, fill=None, gradient=None, stroke=0):
    """居中绘制文本；gradient=(c1,c2) 时以文字形状做渐变填充"""
    font = ImageFont.truetype(font_path, font_size)
    layer = Image.new("L", (SIZE, SIZE), 0)
    ld = ImageDraw.Draw(layer)
    bbox = ld.textbbox((0, 0), text, font=font, stroke_width=stroke)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = (SIZE - tw) // 2 - bbox[0], (SIZE - th) // 2 - bbox[1] - 20  # 视觉重心略上移
    ld.text((x, y), text, font=font, fill=255, stroke_width=stroke, stroke_fill=255)

    if gradient:
        grad = v_gradient(*gradient).convert("RGBA")
        out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        out.paste(grad, (0, 0), layer)
        img.alpha_composite(out)
    else:
        solid = Image.new("RGBA", (SIZE, SIZE), fill + (255,))
        img.alpha_composite(Image.composite(solid, Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)), layer))
    return img


# V1：白字 IU · 靛紫渐变圆角方（扁平常规款）
def v1():
    img = rounded_bg((99, 102, 241), (139, 92, 246))
    size = fit_font_size("IU", FONT_BOLD, 760, stroke=18)
    draw_text_center(img, "IU", FONT_BOLD, size, fill=(255, 255, 255), stroke=18)
    save_all(img, "iu-v1-flat")


def v1_w(target_w, name):
    """验证轮：更大字号候选（等维护者确认后才接入）"""
    img = rounded_bg((99, 102, 241), (139, 92, 246))
    size = fit_font_size("IU", FONT_BOLD, target_w, stroke=18)
    draw_text_center(img, "IU", FONT_BOLD, size, fill=(255, 255, 255), stroke=18)
    save_all(img, name)


def v1_cond(target_w, name, stroke=8):
    """候选：Bahnschrift Bold Condensed —— 同宽度下字母更高，竖向也撑满"""
    img = rounded_bg((99, 102, 241), (139, 92, 246))
    probe = ImageFont.truetype(FONT_DIN, 100)
    probe.set_variation_by_name("Bold Condensed")
    ld = ImageDraw.Draw(Image.new("L", (8, 8)))
    b = ld.textbbox((0, 0), "IU", font=probe, stroke_width=stroke)
    size = int(100 * target_w / (b[2] - b[0]))
    font = ImageFont.truetype(FONT_DIN, size)
    font.set_variation_by_name("Bold Condensed")
    layer = Image.new("L", (SIZE, SIZE), 0)
    ldd = ImageDraw.Draw(layer)
    bbox = ldd.textbbox((0, 0), "IU", font=font, stroke_width=stroke)
    x, y = (SIZE - (bbox[2] - bbox[0])) // 2 - bbox[0], (SIZE - (bbox[3] - bbox[1])) // 2 - bbox[1] - 20
    ldd.text((x, y), "IU", font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    solid = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255))
    img.alpha_composite(Image.composite(solid, Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)), layer))
    save_all(img, name)


# V2：渐变字 IU · 深海军蓝底（青→翠，DIN 风格字体）
def v2():
    img = rounded_bg((15, 23, 42), (30, 41, 59))
    size = fit_font_size("IU", FONT_DIN, 760, stroke=20)
    draw_text_center(img, "IU", FONT_DIN, size, gradient=((34, 211, 238), (52, 211, 153)), stroke=20)
    save_all(img, "iu-v2-glow")


# V3：浅底 + 靛紫渐变字 IU（亮色调，描边圆角框）
def v3():
    img = rounded_bg((248, 250, 252), (224, 231, 240))
    size = fit_font_size("IU", FONT_BOLD, 760, stroke=18)
    draw_text_center(img, "IU", FONT_BOLD, size, gradient=((99, 102, 241), (139, 92, 246)), stroke=18)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([46, 46, SIZE - 46, SIZE - 46], radius=160, outline=(99, 102, 241, 255), width=18)
    save_all(img, "iu-v3-light")


if __name__ == "__main__":
    v1()
    v2()
    v3()
    v1_w(870, "iu-v1-w870")     # 二轮候选 A（约 85%）
    v1_w(950, "iu-v1-w950")     # 二轮候选 B（约 93%）
    v1_w(990, "iu-v1-w990")     # 三轮候选 A：Segoe 极限宽约 97%
    v1_cond(950, "iu-v1-cond950")  # 三轮候选 B：Bold Condensed，同宽更高
