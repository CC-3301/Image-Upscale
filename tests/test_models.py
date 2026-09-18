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
    ("waifu2x_upconv_7_art", 2, (96, 64)),
    ("waifu2x_cunet", 2, (96, 64)),
    ("realcugan-pro", 2, (96, 64)),
    ("realcugan-se", 2, (96, 64)),
    ("realcugan-se", 4, (192, 128)),
    ("digital-art-4x", 4, (192, 128)),
    ("realesr-general-x4v3", 4, (192, 128)),
    ("waifu2x_upconv_7_photo", 2, (96, 64)),
])
def test_all_bundled_models_cpu(workdir, model, scale, outsize):
    p, inp = _smoke(workdir, model, scale)
    assert p.returncode == 0, p.stderr
    out = workdir / f"in-({model})-n0-{scale}.0x.png"
    assert out.exists()
    assert Image.open(out).size == outsize


@needs_engine
def test_denoise_levels_naming_and_success(workdir):
    inp = workdir / "in.png"
    make_png(inp)
    for level, tag in [("low", "n1"), ("mid", "n2"), ("high", "n3")]:
        p = run_engine(["-i", inp, "-m", "waifu2x_cunet", "--denoise", level, "-f", "png", "-g", "-1"])
        assert p.returncode == 0, p.stderr
        out = workdir / f"in-(waifu2x_cunet)-{tag}-2.0x.png"
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
    assert (workdir / "in-(realcugan-se)-n0-3.0x.png").exists()
    # waifu2x_upconv_7_art 无 4x → 参数错误
    p2 = run_engine(["-i", inp, "-m", "waifu2x_upconv_7_art", "-s", "4", "-g", "-1"])
    assert p2.returncode == 1


@needs_engine
def test_denoise_naming_none_writes_n0_segment(workdir):
    """工单 39：无降噪也写 -n0，便于一眼确认降噪档位"""
    inp = workdir / "in.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-m", "waifu2x_cunet", "-f", "png", "-g", "-1"])
    assert p.returncode == 0
    assert (workdir / "in-(waifu2x_cunet)-n0-2.0x.png").exists()
    assert not (workdir / "in-(waifu2x_cunet)-2.0x.png").exists()


# ---- 工单 16 缺陷修复：models/manifest.conf 按引擎自身位置解析，不再强依赖 CWD ----

@needs_engine
def test_models_resolved_relative_to_engine_exe(tmp_path, workdir):
    """模拟 dist 布局：engine/ 子目录放引擎、models/ 在上级；从 tmp_path（引擎目录的上级）运行。
    旧引擎按 CWD 找清单会报 cannot read models/manifest.conf。"""
    import shutil
    import subprocess
    from conftest import ENGINE, REPO

    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    engine_copy = engine_dir / "image-upscale.exe"
    shutil.copy2(ENGINE, engine_copy)
    (tmp_path / "models").mkdir()
    shutil.copy(REPO / "models" / "manifest.conf", tmp_path / "models" / "manifest.conf")

    # GUI 以 engine/ 子目录作为引擎工作目录（MainWindow 传 WorkingDirectory=引擎所在目录），
    # 输入不存在时若清单解析成功会推进到输入校验（"input file not readable"）；
    # 若清单仍按 CWD 解析失败，则是 "cannot read models/manifest.conf"
    p = subprocess.run(
        [str(engine_copy), "-i", str(workdir / "no-such.png"), "-m", "waifu2x_upconv_7_art", "-g", "-1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=engine_dir)
    assert "cannot read models/manifest.conf" not in p.stderr, p.stderr


@needs_engine
def test_explicit_models_dir_wins(tmp_path, workdir):
    """显式 --models-dir 指向他处时不做 fallback 探测，且清单也跟随该目录。"""
    import shutil
    import subprocess
    from conftest import ENGINE, REPO

    alt = tmp_path / "alt-models"
    alt.mkdir()
    shutil.copy(REPO / "models" / "manifest.conf", alt / "manifest.conf")

    # CWD=repo 根（models/ 可用）但显式指定 alt：清单应从 alt 读（同样推进到输入校验）
    p = subprocess.run(
        [str(ENGINE), "-i", str(workdir / "no-such.png"), "-m", "waifu2x_upconv_7_art",
         "--models-dir", str(alt), "-g", "-1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO)
    assert "cannot read models/manifest.conf" not in p.stderr, p.stderr
