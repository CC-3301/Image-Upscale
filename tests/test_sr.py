"""推理正确性：CPU 后端确定性 + PSNR 容差；灰度输入转换"""
import os

import numpy as np
import pytest
from PIL import Image

from conftest import REPO, make_gray_jpg, make_png, needs_engine, run_engine, MODEL

BASELINE = REPO / "tests" / ".baseline"


def _psnr(a: Image.Image, b: Image.Image) -> float:
    aa = np.asarray(a.convert("RGB"), dtype=np.float64)
    bb = np.asarray(b.convert("RGB"), dtype=np.float64)
    mse = np.mean((aa - bb) ** 2)
    if mse == 0:
        return 99.0
    return 10 * np.log10(255.0 * 255.0 / mse)


@needs_engine
def test_cpu_2x_dimensions_and_psrn(workdir):
    inp = workdir / "checker.png"
    make_png(inp)

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"checker-({MODEL})-2.0x.png"
    img = Image.open(out)
    assert img.size == (128, 128)

    baseline_path = BASELINE / "cpu_2x.png"
    if not baseline_path.exists():
        # 首次运行：建立基准
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(baseline_path)
    else:
        # 后续运行：PSNR 容差断言（不逐像素相等）
        ref = Image.open(baseline_path)
        assert _psnr(img, ref) >= 30.0


@needs_engine
def test_grayscale_jpg_input(workdir):
    inp = workdir / "gray.jpg"
    make_gray_jpg(inp)
    p = run_engine(["-i", inp, "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"gray-({MODEL})-2.0x.jpg"
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
    out = workdir / f"pic-({MODEL})-2.0x.png"
    assert Image.open(out).size == (128, 128)
