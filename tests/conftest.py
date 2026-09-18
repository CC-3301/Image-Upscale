import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parent.parent


def _resolve_engine():
    """引擎路径：IU_ENGINE 显式指定 > bld/（本仓库构建产物）> build/Release/（旧布局兜底）。

    默认值曾指向 build/Release/，在本布局下不存在，会让全部用例静默 skip（假绿）。
    """
    env = os.environ.get("IU_ENGINE")
    if env:
        return Path(env)
    legacy = REPO / "build" / "Release" / "image-upscale.exe"
    return legacy if legacy.exists() else REPO / "bld" / "image-upscale.exe"


ENGINE = _resolve_engine()
MODEL = os.environ.get("IU_MODEL", "waifu2x_upconv_7_art")

needs_engine = pytest.mark.skipif(not ENGINE.exists(), reason="engine exe not built")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """防空绿：引擎缺失时全部用例被 skip，pytest 仍退出 0。会话末尾显式告警，别把没跑读成通过。"""
    if ENGINE.exists():
        return
    skipped = [r for r in terminalreporter.stats.get("skipped", []) if "engine exe not built" in str(r.longrepr)]
    if not skipped:
        return
    terminalreporter.write_sep("=", "警告：引擎未构建，测试未真正执行", red=True, bold=True)
    terminalreporter.write_line(f"引擎路径不存在：{ENGINE}")
    terminalreporter.write_line(f"被跳过：{len(skipped)} 个用例 —— 本次全绿不代表通过")
    terminalreporter.write_line("先构建引擎（scripts\\engine-build.bat），或设 IU_ENGINE 指向 image-upscale.exe")


def run_engine(args, cwd=None):
    cmd = [str(ENGINE)] + [str(a) for a in args]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    return p


def make_png(path, size=(64, 64), mode="RGB"):
    """生成确定性测试图：棋盘 + 渐变"""
    w, h = size
    img = Image.new(mode, (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            v = (x * 255 // max(1, w - 1), y * 255 // max(1, h - 1), ((x // 8 + y // 8) % 2) * 255)
            if mode == "RGB":
                px[x, y] = v
            elif mode == "L":
                px[x, y] = v[0]
            elif mode == "RGBA":
                px[x, y] = v + (255 if x < w // 2 else 128)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return img


def make_gray_jpg(path, size=(64, 64)):
    make_png(path.with_suffix(".tmp.png"), size, "L")
    Image.open(path.with_suffix(".tmp.png")).convert("L").save(path, quality=90)
    path.with_suffix(".tmp.png").unlink()


@pytest.fixture
def workdir(tmp_path):
    return tmp_path
