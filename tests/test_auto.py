"""工单 06：AUTO 降噪（伪影估计 → 档位映射）"""
import pytest
from PIL import Image

from conftest import make_png, needs_engine, run_engine


def make_gradient(path, size=(200, 140)):
    w, h = size
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // (w - 1), y * 255 // (h - 1), 128)
    img.save(path)


@needs_engine
def test_auto_clean_image_resolves_level0(workdir):
    inp = workdir / "clean.png"
    make_gradient(inp)
    p = run_engine(["-i", inp, "-m", "cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    assert "denoise: auto resolved level=0" in p.stderr
    out = workdir / "clean-(cunet)-2.0x.png"
    assert out.exists()
    # level 0 → 命名无 n 段
    assert not (workdir / "clean-(cunet)-n1-2.0x.png").exists()


@needs_engine
def test_auto_heavy_jpeg_resolves_strong_level(workdir):
    inp = workdir / "dirty.jpg"
    make_gradient(inp)
    img = Image.open(inp)
    img.save(inp, quality=10)  # 重压缩伪影
    p = run_engine(["-i", inp, "-m", "cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    assert "denoise: auto resolved level=2" in p.stderr or "denoise: auto resolved level=3" in p.stderr
    # 命名含解析档位（n2 或 n3）
    import os
    names = os.listdir(workdir)
    assert any("-n2-" in n or "-n3-" in n for n in names)


@needs_engine
def test_auto_deterministic(workdir):
    inp = workdir / "dirty.jpg"
    make_gradient(inp)
    img = Image.open(inp)
    img.save(inp, quality=10)
    levels = []
    for _ in range(2):
        p = run_engine(["-i", inp, "-m", "cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
        assert p.returncode == 0
        for line in p.stderr.splitlines():
            if "auto resolved level=" in line:
                levels.append(line.split("level=")[1][0])
    assert levels[0] == levels[1]


@needs_engine
def test_auto_unsupported_model_is_param_error(workdir):
    inp = workdir / "in.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-m", "digital-art-4x", "--denoise", "auto", "-g", "-1"])
    assert p.returncode == 1


@needs_engine
def test_auto_multi_scale_model_works(workdir):
    inp = workdir / "in.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-m", "realcugan-se", "--denoise", "auto", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr


@needs_engine
def test_auto_folder_naming_uses_first_file_level(workdir):
    folder = workdir / "manga"
    folder.mkdir()
    make_gradient(folder / "a.png")  # 首文件干净 → level 0 → 文件夹无 n 段
    p = run_engine(["-i", folder, "-m", "cunet", "--denoise", "auto", "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    outdir = workdir / "manga-(cunet)-2.0x"
    assert outdir.is_dir()
    assert (outdir / "a.png").exists()
