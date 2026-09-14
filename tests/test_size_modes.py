"""工单 02：完整尺寸模式（目标尺寸互斥 + 直通缩放）"""
import pytest
from PIL import Image

from conftest import make_png, needs_engine, run_engine


@needs_engine
def test_width_target_above_orig_uses_sr_and_exact_resize(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "192", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-192x.png"
    assert out.exists()
    assert Image.open(out).size == (192, 128)  # 192x128 = 精确目标（等比推算高）


@needs_engine
def test_height_target_naming(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--height", "128", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-128x.png"
    assert out.exists()
    assert Image.open(out).size == (192, 128)


@needs_engine
def test_width_target_below_orig_direct_resize(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "24", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(Resize)-24x.png"
    assert out.exists()
    assert Image.open(out).size == (24, 16)
    # 直通缩放无 n 段
    assert not (workdir / "in-(waifu2x_upconv_7_art)-24x.png").exists()


@needs_engine
def test_width_height_mutually_exclusive(workdir):
    inp = workdir / "in.png"
    make_png(inp)
    p = run_engine(["-i", inp, "--width", "100", "--height", "100"])
    assert p.returncode == 1


@needs_engine
def test_scale_with_width_mutually_exclusive(workdir):
    inp = workdir / "in.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-s", "2", "--width", "100"])
    assert p.returncode == 1


@needs_engine
def test_native_scale_picking_multi_scale_model(workdir):
    # realcugan-se 原生 2/3/4x：宽 150（48→150 比例 3.125）→ 选 4x 超分再精确缩到 150x100
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-m", "realcugan-se", "--width", "150", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(realcugan-se)-150x.png"
    assert out.exists()
    assert Image.open(out).size == (150, 100)


@needs_engine
def test_direct_resize_target_smaller_multi_scale_model(workdir):
    # 目标小于原图 → 即便是多倍数模型也直通缩放（跳过推理）
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-m", "realcugan-se", "--width", "24", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(Resize)-24x.png"
    assert out.exists()
    assert Image.open(out).size == (24, 16)


@needs_engine
def test_folder_target_mode_naming(workdir):
    folder = workdir / "manga"
    folder.mkdir()
    make_png(folder / "p001.png", size=(48, 32))
    p = run_engine(["-i", folder, "--width", "96", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    outdir = workdir / "manga-(waifu2x_upconv_7_art)-96x"
    assert (outdir / "p001.png").exists()
    assert Image.open(outdir / "p001.png").size == (96, 64)


@needs_engine
def test_target_mode_gpu_smoke(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "192", "-f", "png"])
    assert p.returncode == 0, p.stderr
    assert Image.open(workdir / "in-(waifu2x_upconv_7_art)-192x.png").size == (192, 128)


# ---- 工单 10：颜色通道回归（旧引擎在 resize 路径把 RGB 按单通道写出 → 黑白+变形）----

@needs_engine
def test_color_preserved_scale_mode(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-s", "2", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-2.0x.png"
    assert out.exists()
    assert Image.open(out).mode == "RGB"


@needs_engine
def test_color_preserved_width_target_resize_path(workdir):
    # 48x32 → 宽 80：非整倍（比例 1.67 → 原生 2x 后精确 resize），必须保持彩色
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "80", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-80x.png"
    assert out.exists()
    assert Image.open(out).size == (80, 53)  # 等比：32*80/48 = 53.33 → 53
    assert Image.open(out).mode == "RGB"


@needs_engine
def test_color_preserved_width_target_shortcut_path(workdir):
    # 48x32 → 宽 96：整 2 倍捷径（无 resize），同样必须保持彩色
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "96", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-96x.png"
    assert out.exists()
    assert Image.open(out).mode == "RGB"


@needs_engine
def test_color_preserved_direct_resize_path(workdir):
    # 目标小于原图 → 直通缩放路径，同样必须保持彩色
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "24", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(Resize)-24x.png"
    assert out.exists()
    assert Image.open(out).mode == "RGB"


@needs_engine
def test_color_preserved_jpg_output(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "80", "-f", "jpg", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-80x.jpg"
    assert out.exists()
    assert Image.open(out).mode == "RGB"
