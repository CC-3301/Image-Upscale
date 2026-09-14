import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
ENGINE = Path(os.environ.get("IU_ENGINE", REPO / "build" / "Release" / "image-upscale.exe"))
MODEL = os.environ.get("IU_MODEL", "upconv7-anime")

needs_engine = pytest.mark.skipif(not ENGINE.exists(), reason="engine exe not built")


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
