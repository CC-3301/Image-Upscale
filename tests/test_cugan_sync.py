"""CUGAN 同步档位：图块同步路径的输出不得偏离单图块全图推理（工单 38）

Real-CUGAN 的 SE（squeeze-excitation）描述子是**全图**平均量，所以大图分块推理时
必须把描述子在各图块间同步（syncgap）。上游默认档位 3（very rough）把描述子按 32px
小图块平均后全局复用，会把 realcugan-pro / no-denoise 权重推出分布 → 输出崩成彩色噪声。

本测试不依赖真实素材：构造一张局部统计量差异极大的确定性图案，分别走
  * 同步路径（tile 400 < 图宽 512，走 syncgap 分支）
  * 单图块路径（tile 512 = 图宽，走直通分支，描述子天然是全图量）
断言两者不应相差到「灾难级」——同步档位正确时差值来自分块拼接的边界误差，
档位 3 时整幅图都是彩色噪声。
"""
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import REPO, needs_engine, run_engine

MODELS_DIR = Path(os.environ.get("IU_MODELS", REPO / "models"))
MODEL = "realcugan-pro"

needs_model = pytest.mark.skipif(
    not (MODELS_DIR / MODEL / "up2x-no-denoise.param").exists(),
    reason=f"{MODEL} 模型未下载（scripts/fetch-models.ps1）",
)

# 灾难阈值：正确档位下测试图案仍有分块误差，实测约 11% 像素差 >100；
# 档位 3 时约 76%——取 25% 留出双向余量。
CATASTROPHIC_PIXEL_RATIO = 0.25


def make_sync_fixture(path, size=512, block=64):
    """8x8 个图块，按 (bx+by)%4 轮转 黑/白/随机噪声/棋盘——各块统计量差异极大"""
    rng = np.random.default_rng(20260918)
    arr = np.zeros((size, size), dtype=np.uint8)
    grid = size // block
    for by in range(grid):
        for bx in range(grid):
            k = (bx + by) % 4
            ys, xs = by * block, bx * block
            if k == 0:
                tile = np.zeros((block, block), dtype=np.uint8)
            elif k == 1:
                tile = np.full((block, block), 255, dtype=np.uint8)
            elif k == 2:
                tile = rng.integers(0, 256, (block, block), dtype=np.uint8)
            else:
                yy, xx = np.indices((block, block))
                tile = (((xx // 2 + yy // 2) % 2) * 255).astype(np.uint8)
            arr[ys:ys + block, xs:xs + block] = tile
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr).convert("RGB").save(path)
    return path


@needs_engine
@needs_model
def test_sync_path_matches_single_tile(workdir):
    synced = make_sync_fixture(workdir / "sync.png")
    single = make_sync_fixture(workdir / "single.png")

    p = run_engine(["-i", synced, "-m", MODEL, "-s", "2", "-f", "png", "-t", "400"])
    assert p.returncode == 0, p.stderr
    p = run_engine(["-i", single, "-m", MODEL, "-s", "2", "-f", "png", "-t", "512"])
    assert p.returncode == 0, p.stderr

    a = np.asarray(Image.open(workdir / f"sync-({MODEL})-n0-2.0x.png").convert("RGB"), dtype=np.float32)
    b = np.asarray(Image.open(workdir / f"single-({MODEL})-n0-2.0x.png").convert("RGB"), dtype=np.float32)
    assert a.shape == b.shape == (1024, 1024, 3)

    diff = np.abs(a - b).max(axis=2)
    ratio = float((diff > 100).mean())
    assert ratio < CATASTROPHIC_PIXEL_RATIO, (
        f"同步路径与单图块推理差异过大：{ratio:.3f} 像素差 >100（阈值 {CATASTROPHIC_PIXEL_RATIO}）"
    )
