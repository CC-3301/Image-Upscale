"""工单 03：全部打包模型 + 降噪档位映射"""
import pytest
from PIL import Image

from conftest import MODELS_DIR, REPO, make_png, needs_engine, run_engine


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
    # 必须连 iu_engine.dll 一起复制：否则进程在加载导入表时就失败（0xC000013B）——
    # 什么都读不到、stderr 为空，旧版弱断言（只查某错误串不在 stderr）会因此假绿
    shutil.copy2(ENGINE.parent / "iu_engine.dll", engine_dir / "iu_engine.dll")
    (tmp_path / "models").mkdir()
    shutil.copy(MODELS_DIR / "manifest.conf", tmp_path / "models" / "manifest.conf")

    # GUI 以 engine/ 子目录作为引擎工作目录（MainWindow 传 WorkingDirectory=引擎所在目录），
    # 输入不存在时若清单解析成功会推进到输入校验（"input file not readable"）；
    # 若清单仍按 CWD 解析失败，则是 "cannot read models/manifest.conf"
    p = subprocess.run(
        [str(engine_copy), "-i", str(workdir / "no-such.png"), "-m", "waifu2x_upconv_7_art", "-g", "-1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=engine_dir)
    # 正反两面都断言：清单确实被读到（推进到输入校验），而不是「只是没报那句错」
    assert p.returncode == 3, (p.returncode, p.stderr)
    assert "input file not readable" in p.stderr, p.stderr
    assert "cannot read models/manifest.conf" not in p.stderr, p.stderr


@needs_engine
def test_explicit_models_dir_wins(tmp_path, workdir):
    """显式 --models-dir 指向他处时不做 fallback 探测，且清单也跟随该目录。"""
    import shutil
    import subprocess
    from conftest import ENGINE, REPO

    alt = tmp_path / "alt-models"
    alt.mkdir()
    shutil.copy(MODELS_DIR / "manifest.conf", alt / "manifest.conf")

    # CWD=repo 根（models/ 可用）但显式指定 alt：清单应从 alt 读（同样推进到输入校验）
    p = subprocess.run(
        [str(ENGINE), "-i", str(workdir / "no-such.png"), "-m", "waifu2x_upconv_7_art",
         "--models-dir", str(alt), "-g", "-1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=REPO)
    # 同上：显式 --models-dir 时清单从该目录读，且必须推进到输入校验
    assert p.returncode == 3, (p.returncode, p.stderr)
    assert "input file not readable" in p.stderr, p.stderr
    assert "cannot read models/manifest.conf" not in p.stderr, p.stderr


# ---- 工单 46/47 回归：权重损坏要报失败；Real-ESRGAN 不得刷调试输出 ----

MODEL_BIN = MODELS_DIR / "waifu2x_upconv_7_art" / "noise0_scale2.0x_model.bin"
MODEL_PARAM = MODEL_BIN.with_suffix(".param")
needs_model = pytest.mark.skipif(not MODEL_BIN.exists(), reason="模型未下载（scripts/fetch-models.ps1）")


@needs_engine
@needs_model
@pytest.mark.parametrize("corrupt", ["param-garbage", "bin-truncated"])
def test_corrupt_weight_file_is_inference_error(tmp_path, workdir, corrupt):
    """工单 46：权重损坏必须报失败（退出码 2），不能报成功。

    早期 load() 丢弃 net.load_param/load_model 的返回值 → 坏模型照样返回 0，
    GUI 显示“完成”、退出码 0，用户只能靠肉眼发现坏图。
    """
    import shutil

    alt = tmp_path / "models"
    (alt / "waifu2x_upconv_7_art").mkdir(parents=True)
    shutil.copy(MODELS_DIR / "manifest.conf", alt / "manifest.conf")
    alt_param = alt / "waifu2x_upconv_7_art" / MODEL_PARAM.name
    # 两种情形都把真 .bin 放到位：否则旧代码会在「bin 打不开」处返回 -1，
    # 即使有 bug 也会绿（那样测的是缺文件，不是「返回值被丢弃」）
    shutil.copy(MODEL_BIN, alt / "waifu2x_upconv_7_art" / MODEL_BIN.name)
    if corrupt == "param-garbage":
        # .param 首行须是 ncnn 魔数 7767517；换成非模型内容 → load_param 失败
        alt_param.write_bytes(b"not a ncnn param\n")
    else:
        shutil.copy(MODEL_PARAM, alt_param)
        # 权重被截断 → load_model 失败
        (alt / "waifu2x_upconv_7_art" / MODEL_BIN.name).write_bytes(MODEL_BIN.read_bytes()[:1024])

    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-m", "waifu2x_upconv_7_art", "--models-dir", alt, "-f", "png", "-g", "-1"])
    assert p.returncode == 2, (p.returncode, p.stderr)
    assert "model load failed" in p.stderr, p.stderr


@needs_engine
def test_verbose_reports_resolved_model_variant(workdir):
    """工单 06：verbose 要给出「解析档位 → 模型变体文件」的落点（原先只输出档位数字）"""
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-m", "waifu2x_cunet", "--denoise", "mid", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    assert "engine loaded scale=2x denoise=2" in p.stderr, p.stderr
    # mid 档在 waifu2x 清单里映射到 token 2 → noise2_scale2.0x_model.param
    assert "noise2_scale2.0x_model.param" in p.stderr, p.stderr


@needs_engine
def test_engine_relative_models_wins_over_cwd(tmp_path, workdir):
    """工单 16 / lessons §1.4：定位顺序为 exe 目录 > exe 上级 > CWD。

    构造：exe 上一级（tmp/models）放一张含 ghost 的清单，CWD（tmp/cwd/models）放真实清单。
    `-m ghost` 若解析到 exe 侧 → 模型文件缺失 → EXIT_INFER(2)；
    若被 CWD 压过 → unknown model id → EXIT_PARAM(1)。
    """
    import shutil
    import subprocess
    from conftest import ENGINE

    engine_dir = tmp_path / "engine"
    engine_dir.mkdir()
    shutil.copy2(ENGINE, engine_dir / "image-upscale.exe")
    shutil.copy2(ENGINE.parent / "iu_engine.dll", engine_dir / "iu_engine.dll")

    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "manifest.conf").write_text(
        "model ghost\ndisplay ghost\ngroup manga\narch waifu2x\ndir ghost\n"
        "scale 2\nprepad 7\nin Input1\nout Eltwise4\n"
        "denoise none 0\ndenoise low 1\ndenoise mid 2\ndenoise high 3\n",
        encoding="utf-8")

    cwd = tmp_path / "cwd"
    (cwd / "models").mkdir(parents=True)
    shutil.copy(MODELS_DIR / "manifest.conf", cwd / "models" / "manifest.conf")

    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = subprocess.run(
        [str(engine_dir / "image-upscale.exe"), "-i", str(inp), "-m", "ghost", "-g", "-1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    assert p.returncode == 2, (p.returncode, p.stderr)
    assert "model load failed" in p.stderr, p.stderr


@needs_engine
@needs_model
def test_realesrgan_cpu_path_has_no_debug_output(workdir):
    """工单 47：CPU 路径不得向 stderr 打 [DBG] 调试行或逐图块百分比。

    GUI 把无法识别的 stderr 行原样写进日志面板 → 用户日志被英文调试行刷屏；
    进度只应走已文档化的 stdout `progress d/t`。
    """
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-m", "digital-art-4x", "-s", "4", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    assert "[DBG]" not in p.stderr, p.stderr
    assert "%" not in p.stderr, p.stderr
    assert "progress 1/1" in p.stdout, p.stdout
