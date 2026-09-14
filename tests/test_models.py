"""工单 03：全部打包模型 + 降噪档位映射"""
import pytest
from PIL import Image

from conftest import make_png, needs_engine, run_engine


def _smoke(workdir, model, scale):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-m", model, "-s", str(scale), "-f", "png", "-g", "-1"])
    return p, inp


@needs_engine
@pytest.mark.parametrize("model,scale,outsize", [
    ("upconv7-anime", 2, (96, 64)),
    ("cunet", 2, (96, 64)),
    ("realcugan-pro", 2, (96, 64)),
    ("realcugan-se", 2, (96, 64)),
    ("realcugan-se", 4, (192, 128)),
    ("digital-art-4x", 4, (192, 128)),
    ("realesr-general-x4v3", 4, (192, 128)),
    ("upconv7-photo", 2, (96, 64)),
])
def test_all_bundled_models_cpu(workdir, model, scale, outsize):
    p, inp = _smoke(workdir, model, scale)
    assert p.returncode == 0, p.stderr
    out = workdir / f"in-({model})-{scale}.0x.png"
    assert out.exists()
    assert Image.open(out).size == outsize


@needs_engine
def test_denoise_levels_naming_and_success(workdir):
    inp = workdir / "in.png"
    make_png(inp)
    for level, tag in [("low", "n1"), ("mid", "n2"), ("high", "n3")]:
        p = run_engine(["-i", inp, "-m", "cunet", "--denoise", level, "-f", "png", "-g", "-1"])
        assert p.returncode == 0, p.stderr
        out = workdir / f"in-(cunet)-{tag}-2.0x.png"
        assert out.exists(), f"missing {out}"


@needs_engine
def test_denoise_unsupported_level_is_param_error(workdir):
    inp = workdir / "in.png"
    make_png(inp)
    # realcugan-pro 无"低"档；digital-art-4x 完全不支持降噪
    p1 = run_engine(["-i", inp, "-m", "realcugan-pro", "--denoise", "low", "-g", "-1"])
    assert p1.returncode == 1
    p2 = run_engine(["-i", inp, "-m", "digital-art-4x", "--denoise", "high", "-g", "-1"])
    assert p2.returncode == 1


@needs_engine
def test_scale_validation_per_model(workdir):
    inp = workdir / "in.png"
    make_png(inp)
    # realcugan-se 原生 3x
    p = run_engine(["-i", inp, "-m", "realcugan-se", "-s", "3", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    assert (workdir / "in-(realcugan-se)-3.0x.png").exists()
    # upconv7-anime 无 4x → 参数错误
    p2 = run_engine(["-i", inp, "-m", "upconv7-anime", "-s", "4", "-g", "-1"])
    assert p2.returncode == 1


@needs_engine
def test_denoise_naming_none_has_no_segment(workdir):
    inp = workdir / "in.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-m", "cunet", "-f", "png", "-g", "-1"])
    assert p.returncode == 0
    assert (workdir / "in-(cunet)-2.0x.png").exists()
    assert not (workdir / "in-(cunet)-n0-2.0x.png").exists()
