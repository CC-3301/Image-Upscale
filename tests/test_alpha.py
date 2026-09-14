"""工单 04：alpha 透明通道"""
import pytest
from PIL import Image

from conftest import needs_engine, run_engine


def make_rgba(path, size=(48, 32)):
    """左半不透明（红），右半全透明（蓝）"""
    w, h = size
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            if x < w // 2:
                px[x, y] = (200, 30, 40, 255)
            else:
                px[x, y] = (10, 20, 220, 0)
    img.save(path)
    return img


@needs_engine
def test_alpha_png_preserved(workdir):
    inp = workdir / "in.png"
    make_rgba(inp)
    p = run_engine(["-i", inp, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(upconv7-anime)-2.0x.png"
    assert out.exists()
    img = Image.open(out)
    assert img.mode == "RGBA"
    px = img.load()
    # 不透明区 alpha 保持 255
    assert px[10, 10][3] == 255
    # 透明区 alpha 仍为 0（同步放大后未被破坏）
    assert px[80, 10][3] == 0


@needs_engine
def test_alpha_webp_preserved(workdir):
    inp = workdir / "in.png"
    make_rgba(inp)
    p = run_engine(["-i", inp, "-f", "webp", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(upconv7-anime)-2.0x.webp"
    assert out.exists()
    img = Image.open(out)
    assert img.mode == "RGBA"
    px = img.load()
    assert px[10, 10][3] == 255
    assert px[80, 10][3] == 0


@needs_engine
def test_alpha_jpg_white_composite(workdir):
    inp = workdir / "in.png"
    make_rgba(inp)
    p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(upconv7-anime)-2.0x.jpg"
    assert out.exists()
    img = Image.open(out)
    assert img.mode == "RGB"
    px = img.load()
    # 不透明区保持红色（超分后颜色近似）
    r, g, b = px[10, 10]
    assert r > 150 and g < 100
    # 透明区与白色合成（非黑底）
    r, g, b = px[80, 10]
    assert r > 200 and g > 200 and b > 200


@needs_engine
def test_alpha_direct_resize_keeps_alpha(workdir):
    inp = workdir / "in.png"
    make_rgba(inp)
    p = run_engine(["-i", inp, "--width", "24", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(Resize)-24x.png"
    assert out.exists()
    img = Image.open(out)
    assert img.mode == "RGBA"
    px = img.load()
    assert px[5, 5][3] == 255
    assert px[20, 5][3] == 0


@needs_engine
def test_no_alpha_no_regression(workdir):
    from conftest import make_png
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(upconv7-anime)-2.0x.png"
    img = Image.open(out)
    assert img.mode == "RGB"
