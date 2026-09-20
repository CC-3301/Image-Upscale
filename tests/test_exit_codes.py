"""退出码语义：0 成功 / 1 参数错误 / 2 模型或推理失败 / 3 IO 错误"""
import pytest

from conftest import make_png, needs_engine, run_engine


@needs_engine
def test_missing_input_is_param_error():
    p = run_engine(["-g", "-1"])
    assert p.returncode == 1


@needs_engine
def test_unsupported_scale_is_param_error(workdir):
    inp = workdir / "A.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-s", "3"])
    assert p.returncode == 1


@needs_engine
def test_invalid_quality_is_param_error(workdir):
    inp = workdir / "A.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-q", "101"])
    assert p.returncode == 1


@needs_engine
def test_invalid_format_is_param_error(workdir):
    inp = workdir / "A.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-f", "bmp"])
    assert p.returncode == 1


@needs_engine
def test_unknown_model_type_is_param_error(workdir):
    inp = workdir / "A.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-m", "not-a-model", "-g", "-1"])
    assert p.returncode == 1


@needs_engine
def test_missing_model_files_is_infer_error(workdir):
    inp = workdir / "A.png"
    make_png(inp)
    # 自建 manifest：id 指向不存在的模型目录 → 文件缺失 → 优雅 EXIT_INFER（而非段错误）
    md = workdir / "models"
    md.mkdir()
    (md / "manifest.conf").write_text(
        "model ghost\ndisplay ghost\ngroup manga\narch waifu2x\ndir ghost\n"
        "scale 2\nprepad 7\nin Input1\nout Eltwise4\n"
        "denoise none 0\ndenoise low 1\ndenoise mid 2\ndenoise high 3\n",
        encoding="utf-8")
    p = run_engine(["-i", inp, "-m", "ghost", "--models-dir", md, "-g", "-1"])
    assert p.returncode == 2


@needs_engine
def test_nonexistent_input_is_io_error():
    p = run_engine(["-i", "Z:/no/such/file.png", "-g", "-1"])
    assert p.returncode == 3


@needs_engine
def test_empty_folder_is_param_error(workdir):
    folder = workdir / "empty"
    folder.mkdir()
    p = run_engine(["-i", folder, "-g", "-1"])
    assert p.returncode == 1


@needs_engine
def test_unsupported_input_extension_is_param_error(workdir):
    inp = workdir / "A.gif"
    make_png(inp)  # 真 GIF（make_png 按传入路径的后缀编码）：拒绝理由是扩展名不受支持
    p = run_engine(["-i", inp, "-g", "-1"])
    assert p.returncode == 1
