"""工单 02：完整尺寸模式（目标尺寸互斥 + 直通缩放）"""
import math

import numpy as np
import pytest
from PIL import Image

from conftest import make_png, needs_engine, run_engine


@needs_engine
def test_width_target_above_orig_uses_sr_and_exact_resize(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "192", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-n0-192x.png"
    assert out.exists()
    assert Image.open(out).size == (192, 128)  # 192x128 = 精确目标（等比推算高）


@needs_engine
def test_height_target_naming(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--height", "128", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-n0-128x.png"
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
    assert not (workdir / "in-(waifu2x_upconv_7_art)-n0-24x.png").exists()


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
    out = workdir / "in-(realcugan-se)-n0-150x.png"
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
    outdir = workdir / "manga-(waifu2x_upconv_7_art)-n0-96x"
    assert (outdir / "p001.png").exists()
    assert Image.open(outdir / "p001.png").size == (96, 64)


@needs_engine
def test_target_mode_gpu_smoke(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "192", "-f", "png"])
    assert p.returncode == 0, p.stderr
    assert Image.open(workdir / "in-(waifu2x_upconv_7_art)-n0-192x.png").size == (192, 128)


# ---- 工单 10：颜色通道回归（旧引擎在 resize 路径把 RGB 按单通道写出 → 黑白+变形）----

@needs_engine
def test_color_preserved_scale_mode(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-s", "2", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-n0-2.0x.png"
    assert out.exists()
    assert Image.open(out).mode == "RGB"


@needs_engine
def test_color_preserved_width_target_resize_path(workdir):
    # 48x32 → 宽 80：非整倍（比例 1.67 → 原生 2x 后精确 resize），必须保持彩色
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "80", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-n0-80x.png"
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
    out = workdir / "in-(waifu2x_upconv_7_art)-n0-96x.png"
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
    out = workdir / "in-(waifu2x_upconv_7_art)-n0-80x.jpg"
    assert out.exists()
    assert Image.open(out).mode == "RGB"


def _make_fine_png(path, size=(48, 32)):
    """细网点图：1~2 像素周期的点阵 + 硬边缘，专门放大缩放滤镜之间的差异"""
    w, h = size
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            v = 255 if ((x % 3) or (y % 2)) else 0
            if x > w * 2 // 3:
                v = 0 if (y // 4) % 2 else 255
            px[x, y] = (v, v, v)
    img.save(path)


def _psnr(a, b):
    aa = a.astype("float64")
    bb = b.astype("float64")
    mse = ((aa - bb) ** 2).mean()
    return 99.0 if mse == 0 else 10 * math.log10(255.0 * 255.0 / mse)


@needs_engine
def test_resize_down_filter_default_is_lanczos(workdir):
    """工单 42：目标尺寸模式的缩小默认用 Lanczos

    waifu2x-caffe 的最终缩放在 <0.5 倍时才用面积平均，其余是 INTER_CUBIC；
    本项目把这一步做成可选，默认 Lanczos（最锐）。
    """
    inp = workdir / "fine.png"
    _make_fine_png(inp)
    p = run_engine(["-i", inp, "--width", "37", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / "fine-(Resize)-37x.png"
    assert out.exists()
    assert Image.open(out).size == (37, 25)  # 32 * 37 / 48 + 0.5 → 25

    eng = np.asarray(Image.open(out).convert("RGB"))
    src = Image.open(inp).convert("RGB")
    ref = {n: np.asarray(src.resize((37, 25), f)) for n, f in
           (("lanczos", Image.LANCZOS), ("catmullrom", Image.BICUBIC), ("box", Image.BOX))}
    assert _psnr(eng, ref["lanczos"]) >= 40.0    # 实测 46.5
    assert _psnr(eng, ref["catmullrom"]) <= 35.0  # 不是 Catmull-Rom（实测 30.5）
    assert _psnr(eng, ref["box"]) <= 30.0        # 更不是面积平均（实测 14.0）


@needs_engine
def test_resize_down_filter_selection(workdir):
    """工单 42：四个档位都能选，且结果互不相同（禁止退化成同一个滤镜）"""
    outs = {}
    for token in ("lanczos", "catmullrom", "bicubic", "box"):
        inp = workdir / f"fine_{token}.png"
        _make_fine_png(inp)
        p = run_engine(["-i", inp, "--width", "37", "-f", "png", "-g", "-1", "--down-filter", token])
        assert p.returncode == 0, p.stderr
        outs[token] = np.asarray(Image.open(workdir / f"fine_{token}-(Resize)-37x.png").convert("RGB"))
    for a in outs:
        for b in outs:
            if a < b:
                # 实测两两最高 33.4 dB（box vs catmullrom），阈值 40 留出余量
                assert _psnr(outs[a], outs[b]) <= 40.0, f"{a} 与 {b} 输出过于接近"

    src = Image.open(workdir / "fine_catmullrom.png").convert("RGB")
    # 界面 Catmull-Rom 的核就是 Catmull-Rom；界面 Bicubic 的核是 Mitchell（比它柔）
    assert _psnr(outs["catmullrom"], np.asarray(src.resize((37, 25), Image.BICUBIC))) >= 45.0  # 实测 50.0
    assert _psnr(outs["lanczos"], np.asarray(src.resize((37, 25), Image.LANCZOS))) >= 40.0    # 实测 46.5
    assert _psnr(outs["bicubic"], np.asarray(src.resize((37, 25), Image.BICUBIC))) <= 35.0    # Mitchell ≠ Catmull-Rom


@needs_engine
def test_resize_down_filter_unsupported_rejected(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "--width", "24", "-f", "png", "-g", "-1", "--down-filter", "nope"])
    assert p.returncode != 0
    assert "invalid --down-filter" in p.stderr


@needs_engine
def test_target_above_native_uses_model_passes(workdir):
    """工单 43：放大不用插值 —— 2x 模型要 4 倍时，应等于把模型跑两遍

    对齐 waifu2x 的行为：超过原生倍率时循环跑模型直到达标，收尾只做缩小。
    """
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))

    # 目标 192 = 4x（原生 2x）→ 计划 [2,2]，累积尺寸正好等于目标 → 收尾不缩放
    p = run_engine(["-i", inp, "--width", "192", "-f", "png", "-g", "-1", "-t", "64"])
    assert p.returncode == 0, p.stderr
    once = workdir / "in-(waifu2x_upconv_7_art)-n0-192x.png"
    assert Image.open(once).size == (192, 128)
    direct = np.asarray(Image.open(once).convert("RGB"))

    # 手工跑两遍 2x（第二遍输入是第一遍的产物）
    mid = workdir / "mid.png"
    Image.open(once).close()
    step1 = workdir / "step1.png"
    Image.open(inp).save(step1)
    p = run_engine(["-i", step1, "-s", "2", "-f", "png", "-g", "-1", "-t", "64"])
    assert p.returncode == 0, p.stderr
    first = workdir / "step1-(waifu2x_upconv_7_art)-n0-2.0x.png"
    assert Image.open(first).size == (96, 64)
    Image.open(first).save(mid)
    p = run_engine(["-i", mid, "-s", "2", "-f", "png", "-g", "-1", "-t", "64"])
    assert p.returncode == 0, p.stderr
    second = workdir / "mid-(waifu2x_upconv_7_art)-n0-2.0x.png"
    assert Image.open(second).size == (192, 128)

    assert _psnr(direct, np.asarray(Image.open(second).convert("RGB"))) >= 45.0


@needs_engine
def test_target_between_scales_shrinks_the_model_result(workdir):
    """工单 43：3 倍目标（原生 2x）→ 跑两遍模型到 4x，再缩小到 3x（不是插值放大）"""
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))

    p = run_engine(["-i", inp, "--width", "144", "-f", "png", "-g", "-1", "-t", "64"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(waifu2x_upconv_7_art)-n0-144x.png"
    assert Image.open(out).size == (144, 96)
    got = np.asarray(Image.open(out).convert("RGB"))

    # 参考 A：模型 4x 结果（= --width 192）用 PIL Lanczos 缩到 144x96
    p = run_engine(["-i", inp, "--width", "192", "-f", "png", "-g", "-1", "-t", "64"])
    assert p.returncode == 0, p.stderr
    four = Image.open(workdir / "in-(waifu2x_upconv_7_art)-n0-192x.png").convert("RGB")
    ref_shrink = np.asarray(four.resize((144, 96), Image.LANCZOS))

    # 参考 B（旧行为）：模型 2x 结果直接插值放大到 3x
    p = run_engine(["-i", inp, "-s", "2", "-f", "png", "-g", "-1", "-t", "64"])
    assert p.returncode == 0, p.stderr
    two = Image.open(workdir / "in-(waifu2x_upconv_7_art)-n0-2.0x.png").convert("RGB")
    ref_upscale = np.asarray(two.resize((144, 96), Image.LANCZOS))

    assert _psnr(got, ref_shrink) >= 45.0    # 与“4x 再缩小”一致（实测 56.5）
    assert _psnr(got, ref_upscale) <= 40.0   # 明显不是“2x 再插值放大”（实测 33.5）


@needs_engine
def test_exact_native_multiple_has_no_resize(workdir):
    """工单 43：目标正好是原生倍率整数倍时收尾不缩放 —— 换 --down-filter 输出逐位相同"""
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    name = "in-(waifu2x_upconv_7_art)-n0-96x.png"
    blobs = []
    for token in ("lanczos", "box"):
        p = run_engine(["-i", inp, "--width", "96", "-f", "png", "-g", "-1", "-t", "64", "--down-filter", token])
        assert p.returncode == 0, p.stderr
        blobs.append((workdir / name).read_bytes())
        (workdir / name).unlink()
    assert blobs[0] == blobs[1]


@needs_engine
def test_target_between_native_scales_prefers_single_pass(workdir):
    """工单 43：2.5 倍目标 + 2/3 原生档 → 单轮 3x 再缩小（不是两轮 2x）

    计划规则是“轮数最少，再取累积倍率最小”，所以有单档 ≥ 目标倍率时就用那一档。
    """
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))

    p = run_engine(["-i", inp, "-m", "realcugan-pro", "--width", "120", "-f", "png", "-g", "-1", "-t", "64"])
    assert p.returncode == 0, p.stderr
    out = workdir / "in-(realcugan-pro)-n0-120x.png"
    assert Image.open(out).size == (120, 80)
    got = np.asarray(Image.open(out).convert("RGB"))

    p = run_engine(["-i", inp, "-m", "realcugan-pro", "-s", "3", "-f", "png", "-g", "-1", "-t", "64"])
    assert p.returncode == 0, p.stderr
    three = Image.open(workdir / "in-(realcugan-pro)-n0-3.0x.png").convert("RGB")
    assert three.size == (144, 96)
    ref = np.asarray(three.resize((120, 80), Image.LANCZOS))

    assert _psnr(got, ref) >= 45.0  # 实测 55.3
