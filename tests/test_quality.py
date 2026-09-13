"""质量参数：作用于 jpg/webp，不影响 png"""
import pytest
from PIL import Image

from conftest import make_png, needs_engine, run_engine


@needs_engine
def test_jpg_quality_orders_file_sizes(workdir):
    inp = workdir / "A.png"
    make_png(inp, size=(128, 128))

    low = workdir / f"A-(upconv_7_anime_style_art_rgb)-2.0x-q50.jpg"
    high = workdir / f"A-(upconv_7_anime_style_art_rgb)-2.0x-q95.jpg"

    # 质量段不进命名（01 命名规则无质量段），分别跑后改名收集
    p1 = run_engine(["-i", inp, "-f", "jpg", "-q", "50", "-g", "-1"])
    assert p1.returncode == 0
    out1 = workdir / "A-(upconv_7_anime_style_art_rgb)-2.0x.jpg"
    out1.rename(low)

    p2 = run_engine(["-i", inp, "-f", "jpg", "-q", "95", "-g", "-1"])
    assert p2.returncode == 0
    out2 = workdir / "A-(upconv_7_anime_style_art_rgb)-2.0x.jpg"

    assert low.stat().st_size < out2.stat().st_size
    # 回归：out2 存在即覆盖语义正常
    assert out2.exists()


@needs_engine
def test_png_ignores_quality(workdir):
    inp = workdir / "A.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-f", "png", "-q", "10", "-g", "-1"])
    assert p.returncode == 0
    out = workdir / "A-(upconv_7_anime_style_art_rgb)-2.0x.png"
    assert out.exists()


@needs_engine
def test_webp_quality_valid(workdir):
    inp = workdir / "A.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-f", "webp", "-q", "80", "-g", "-1"])
    assert p.returncode == 0
    out = workdir / "A-(upconv_7_anime_style_art_rgb)-2.0x.webp"
    with open(out, "rb") as f:
        head = f.read(12)
    assert head[:4] == b"RIFF" and head[8:12] == b"WEBP"
