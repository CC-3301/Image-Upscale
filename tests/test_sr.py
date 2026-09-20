"""推理正确性：CPU 后端确定性 + PSNR 容差；灰度输入转换"""
import os

import pytest
from PIL import Image

from conftest import MODELS_DIR, REPO, make_jpg, make_png, make_webp, needs_engine, psnr, run_engine, MODEL

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
        # 基准图已随仓库分发（tests/.baseline/cpu_2x.png 入库）：缺失说明被删除或未同步。
        # 重新生成后本用例仍跳过判定（基准是黄金参考，只能人工确认无误），并由 conftest
        # 的「跳过可见化」在会话末尾告警，不会假绿。
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(baseline_path)
        pytest.skip(f"PSNR 基准缺失，已重新生成 {baseline_path}；与 git 中的版本核对后重跑")

    # 后续运行：PSNR 容差断言（不逐像素相等）
    ref = Image.open(baseline_path)
    assert psnr(img, ref) >= 30.0


@needs_engine
def test_grayscale_jpg_input(workdir):
    inp = workdir / "gray.jpg"
    make_jpg(inp)
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
    make_webp(inp, lossless=True)

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"pic-({MODEL})-n0-2.0x.png"
    assert Image.open(out).size == (128, 128)
