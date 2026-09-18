"""Real-CUGAN pro 的输入/输出仿射归一化（工单 40）

官方 Real-CUGAN 对 **pro 系权重**（`weights_pro/*.pth` → models-pro / models-nose）在
pytorch 侧做了仿射归一化（upcunet_v3.py 的 `np2tensor` / `forward`）：

    np2tensor:  x/255 * 0.7 + 0.15          （[0,1] → [0.15, 0.85]）
    forward:    (y - 0.15) * 255 / 0.7

nihui 的 ncnn 移植漏了这对变换（上游 issue #52，至今未修），本项目引擎此前照搬该移植，
于是 pro 权重实际运行在训练分布之外：普通内容上看不出（网络近似仿射等变，两次变换近似相消），
但遇到高对比网点类内容会整幅崩成彩色噪声。

夹具：256×256 黑底稀疏白点（印刷网点的高对比抽象）。实测 chroma>40 像素占比：
    修复前 GPU(fp16) 0.667（整幅彩色噪声）
    修复后 GPU 0.029 / CPU 0.029

测试固定 `-g 0`（GPU）：本缺陷在 GPU 上表现最剧烈，也是用户实际路径；无 Vulkan 设备时跳过。
同夹具下 cugan 的 **CPU 与 GPU 后端会给出完全不同的结果**（各自逐位可复现，官方 ncnn 二进制同样如此）——该现象已核查为非代码逻辑缺陷（真实素材不触发、谁对无定论），不建档、不作为本测试的断言依据。
"""
import numpy as np
import pytest
from PIL import Image

from conftest import MODELS_DIR, needs_engine, run_engine

MODEL = "realcugan-pro"

needs_model = pytest.mark.skipif(
    not (MODELS_DIR / MODEL / "up2x-no-denoise.param").exists(),
    reason=f"{MODEL} 模型未下载（scripts/fetch-models.ps1）",
)

# 修复前 0.667，修复后 0.029；取 0.10 留约 3 倍双向余量
MAX_CHROMA_NOISE = 0.10


def _sparse_dots(size=256):
    """黑底 + 稀疏白点（8px 栅格）与一层浅灰偏移点"""
    a = np.zeros((size, size), dtype=np.uint8)
    a[8::8, 8::8] = 255
    a[4::8, 4::8] = 200
    return a


def _chroma_noise_ratio(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)
    chroma = a.max(axis=2) - a.min(axis=2)
    return float((chroma > 40).mean())


@needs_engine
@needs_model
def test_pro_model_has_no_chroma_blowup_on_halftone(workdir):
    inp = workdir / "halftone.png"
    Image.fromarray(_sparse_dots()).convert("RGB").save(inp)

    p = run_engine(["-i", inp, "-m", MODEL, "-s", "2", "-f", "png", "-g", "0"])
    if p.returncode == 1 and "invalid gpu device" in p.stderr:
        pytest.skip("无 Vulkan 设备；本缺陷只在 GPU(fp16) 路径复现，CPU 路径不作断言")
    assert p.returncode == 0, p.stderr

    out = workdir / f"halftone-({MODEL})-n0-2.0x.png"
    assert out.exists()
    ratio = _chroma_noise_ratio(out)
    assert ratio < MAX_CHROMA_NOISE, (
        f"pro 输出彩色噪声占比 {ratio:.3f}（阈值 {MAX_CHROMA_NOISE}）"
        "——pro 系权重的 [0.15,0.85] 归一化未生效"
    )
