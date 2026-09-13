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
    # 已知类型（upconv）但模型文件不存在 → 模型加载失败 → 2
    p = run_engine(["-i", inp, "-m", "upconv_7_photo", "-g", "-1"])
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
    make_png(inp)  # 内容 png 但后缀 gif → 后缀匹配拒绝
    p = run_engine(["-i", inp, "-g", "-1"])
    assert p.returncode == 1
