import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
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
# 模型目录：与引擎同样的优先序（显式环境变量 > 仓库 models/）；各测试统一从这里取
MODELS_DIR = Path(os.environ.get("IU_MODELS", REPO / "models"))

needs_engine = pytest.mark.skipif(not ENGINE.exists(), reason="engine exe not built")


def _skip_reason(report):
    """从 skip report 里取出原因（skipif 的 longrepr 是 (file, line, reason) 三元组）"""
    lr = getattr(report, "longrepr", "")
    if isinstance(lr, tuple) and len(lr) >= 3:
        return str(lr[2])
    return str(getattr(report, "reason", "")) or str(lr)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """防空绿：被跳过的用例必须在会话末尾显式可见，否则「没跑」会被读成「通过」。

    三类会产生 skip：引擎未构建、PSNR 基准首次生成、模型未下载（fetch-models 未跑）。
    """
    skipped = terminalreporter.stats.get("skipped", [])
    if not skipped:
        return
    if ENGINE.exists():
        terminalreporter.write_sep("=", f"注意：{len(skipped)} 个用例被跳过", yellow=True, bold=True)
    else:
        terminalreporter.write_sep("=", "警告：引擎未构建，测试未真正执行", red=True, bold=True)
        terminalreporter.write_line(f"引擎路径不存在：{ENGINE}")
        terminalreporter.write_line("先构建引擎（scripts\\engine-build.bat），或设 IU_ENGINE 指向 image-upscale.exe")
    terminalreporter.write_line(f"被跳过：{len(skipped)} 个用例 —— 本次全绿不代表这些用例通过")
    for report in skipped[:10]:
        terminalreporter.write_line(f"  · {report.nodeid}：{_skip_reason(report)}")
    if len(skipped) > 10:
        terminalreporter.write_line(f"  · ……另有 {len(skipped) - 10} 个")


def psnr(a, b):
    """PSNR（dB）：入参可为 PIL.Image 或 numpy 数组；mse==0 时返回 99.0 作上限哨兵"""
    aa = np.asarray(a.convert("RGB") if hasattr(a, "convert") else a, dtype=np.float64)
    bb = np.asarray(b.convert("RGB") if hasattr(b, "convert") else b, dtype=np.float64)
    mse = ((aa - bb) ** 2).mean()
    return 99.0 if mse == 0 else 10 * math.log10(255.0 * 255.0 / mse)


def run_engine(args, cwd=None):
    cmd = [str(ENGINE)] + [str(a) for a in args]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd)
    return p


def _checker_img(size=(64, 64), mode="RGB"):
    """确定性测试图内容：棋盘 + 渐变（各夹具 helper 共用图案，编码格式由调用者决定）"""
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
    return img


def make_png(path, size=(64, 64), mode="RGB"):
    """生成确定性测试图：棋盘 + 渐变（不传 format，编码按传入路径的后缀推断 → 传 `.gif` 即真 GIF）"""
    img = _checker_img(size, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return img


def make_jpg(path, size=(64, 64)):
    """真 JPEG 夹具（灰度内容），只供结构型断言：退出码 / 尺寸 / 格式

    命名按格式统一（make_png / make_jpg / make_webp）；灰度来自最初的用途（test_sr 的灰度输入
    用例），test_naming 则拿它当「非 PNG 的真 JPEG」。内容质量判据用 make_png / make_gradient。
    """
    img = _checker_img(size, "L")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, quality=90)
    return img


def make_webp(path, size=(64, 64), lossless=False):
    """真 WEBP 夹具（显式 `format="WEBP"`，与后缀无关；`lossless` 供不希望引入压缩伪影的用例）"""
    img = _checker_img(size)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="WEBP", lossless=lossless)
    return img


def make_gradient(path, size=(200, 140)):
    """连续色调渐变图（AUTO 估计用：干净 = 0 档；重压缩后非 0 档）"""
    w, h = size
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // (w - 1), y * 255 // (h - 1), 128)
    img.save(path)
    return img


# AUTO 逐文件档位在 verbose stderr 上的标记（解析口径只写一份，供下面两个视图共用）
_AUTO_LEVEL_MARK = "auto resolved level="


def resolved_levels(stderr):
    """从引擎 stderr 取 AUTO 逐文件解析出的降噪档位（**按处理顺序**的一串）"""
    return [int(l.split(_AUTO_LEVEL_MARK)[1])
            for l in stderr.splitlines() if _AUTO_LEVEL_MARK in l]


def auto_levels_by_file(stderr):
    """同上，但按**文件路径**索引（不依赖处理顺序：目录遍历顺序不是排序的）。

    verbose 下每个文件先打 "loaded <path> (WxH)"、紧跟着才打 "auto resolved level=N"，
    所以按这个先后配对就能把档位归到具体文件；目录批量用例要断言「某文件用的是自己解析出的档位」
    时用这个视图，不能靠 `resolved_levels` 的下标。
    """
    out = {}
    cur = None
    for line in stderr.splitlines():
        if line.startswith("loaded "):
            cur = line[len("loaded "):].rsplit(" (", 1)[0]
        elif _AUTO_LEVEL_MARK in line and cur:
            out[cur] = int(line.split(_AUTO_LEVEL_MARK)[1])
            cur = None
    return out


@pytest.fixture
def workdir(tmp_path):
    return tmp_path
