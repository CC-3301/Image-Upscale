"""推理正确性：CPU 后端确定性 + PSNR 容差；灰度输入转换"""
import os

import pytest
from PIL import Image

from conftest import MODELS_DIR, REPO, make_gray_jpg, make_png, needs_engine, psnr, run_engine, MODEL

BASELINE = REPO / "tests" / ".baseline"


@needs_engine
def test_cpu_2x_dimensions_and_psrn(workdir):
    inp = workdir / "checker.png"
    make_png(inp)

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"checker-({MODEL})-n0-2.0x.png"
    img = Image.open(out)
    assert img.size == (128, 128)

    baseline_path = BASELINE / "cpu_2x.png"
    if not baseline_path.exists():
        # 首次运行：建立基准。基准是「人工确认过的黄金参考」，无法自动判定，
        # 所以本次只生成、不判定通过（原先自动生成 + 不断言 → 新机器上永远全绿）
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(baseline_path)
        pytest.skip(f"PSNR 基准首次生成 {baseline_path}：人工确认输出无误后重跑本用例才算通过")

    # 后续运行：PSNR 容差断言（不逐像素相等）
    ref = Image.open(baseline_path)
    assert psnr(img, ref) >= 30.0


@needs_engine
def test_grayscale_jpg_input(workdir):
    inp = workdir / "gray.jpg"
    make_gray_jpg(inp)
    p = run_engine(["-i", inp, "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"gray-({MODEL})-n0-2.0x.jpg"
    img = Image.open(out)
    assert img.size == (128, 128)
    # 输出应为 RGB 语义（JPG 无 alpha）
    assert img.mode in ("RGB", "L")


@needs_engine
def test_webp_input_decode(workdir):
    inp = workdir / "pic.webp"
    make_png(inp.with_suffix(".tmp.png"))
    Image.open(inp.with_suffix(".tmp.png")).save(inp, format="WEBP", lossless=True)
    inp.with_suffix(".tmp.png").unlink()

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"pic-({MODEL})-n0-2.0x.png"
    assert Image.open(out).size == (128, 128)
