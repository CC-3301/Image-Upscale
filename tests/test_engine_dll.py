"""工单 27：iu_engine.dll 的 P/Invoke 面冒烟（ctypes 直调，锁住 GUI 依赖的导出契约）

GUI（ImageUpscale.exe）经 DllImport 调用 iu_run(argc, argv, out_cb, err_cb, user)；
本测试用同一签名直调，验证退出码、行协议（progress / -> done / done）与产物落盘。
"""
import ctypes
import os
from pathlib import Path

import pytest
from PIL import Image

from conftest import REPO, make_png

DLL = Path(os.environ.get("IU_ENGINE_DLL", REPO / "bld" / "iu_engine.dll"))
MODELS = REPO / "models"

needs_dll = pytest.mark.skipif(not DLL.exists(), reason="iu_engine.dll not built")

LINE_CB = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)


def run_dll(args):
    """直调 iu_run；返回 (退出码, stdout行列表, stderr行列表)。回调行含结尾换行。"""
    lib = ctypes.CDLL(str(DLL))
    lib.iu_run.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_wchar_p), LINE_CB, LINE_CB, ctypes.c_void_p]
    lib.iu_run.restype = ctypes.c_int

    out_lines, err_lines = [], []

    def on_out(line, _user):
        out_lines.append(line.decode("utf-8", "replace"))

    def on_err(line, _user):
        err_lines.append(line.decode("utf-8", "replace"))

    cb_out = LINE_CB(on_out)
    cb_err = LINE_CB(on_err)
    argv = (ctypes.c_wchar_p * (len(args) + 1))("ImageUpscale", *[str(a) for a in args])
    rc = lib.iu_run(len(argv), argv, cb_out, cb_err, None)
    return rc, out_lines, err_lines


@needs_dll
def test_dll_single_file_success(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    rc, out_lines, err_lines = run_dll(
        ["-i", inp, "-m", "waifu2x_upconv_7_art", "-s", "2", "-f", "png", "-g", "-1",
         "--models-dir", MODELS])
    assert rc == 0, err_lines
    # 行协议（GUI 解析同款）：进度行 / 成功行（" done" 后缀）/ 终行 done
    assert "progress 1/1\n" in out_lines
    assert any(l.endswith(" done\n") and " -> " in l for l in out_lines)
    assert "done\n" in out_lines
    out = workdir / "in-(waifu2x_upconv_7_art)-n0-2.0x.png"
    assert out.exists()
    assert Image.open(out).size == (96, 64)


@needs_dll
def test_dll_param_error_exit_code(workdir):
    rc, out_lines, err_lines = run_dll(
        ["-i", workdir / "no-such.png", "-m", "no-such-model", "--models-dir", MODELS])
    assert rc == 1
    assert any("unknown model id" in l for l in err_lines)
