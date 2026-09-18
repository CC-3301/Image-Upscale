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
    p = run_engine(["-i", inp, "-m", "waifu2x_cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    assert "denoise: auto resolved level=0" in p.stderr
    out = workdir / "clean-(waifu2x_cunet)-n0-2.0x.png"
    assert out.exists()
    # level 0 → 命名写 -n0（工单 39）
    assert not (workdir / "clean-(waifu2x_cunet)-n1-2.0x.png").exists()


@needs_engine
def test_auto_heavy_jpeg_resolves_strong_level(workdir):
    inp = workdir / "dirty.jpg"
    make_gradient(inp)
    img = Image.open(inp)
    img.save(inp, quality=10)  # 重压缩伪影
    p = run_engine(["-i", inp, "-m", "waifu2x_cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
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
        p = run_engine(["-i", inp, "-m", "waifu2x_cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
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


def _resolved_levels(stderr):
    return [int(l.split("auto resolved level=")[1])
            for l in stderr.splitlines() if "auto resolved level=" in l]


@needs_engine
def test_auto_folder_uniform_level_folder_uses_it_and_keeps_names(workdir):
    """工单 39：全批档位一致 → 目录名写该档位，内部文件名原样镜像"""
    folder = workdir / "manga"
    folder.mkdir()
    make_gradient(folder / "a.png")  # 干净 → level 0
    make_gradient(folder / "b.png")
    p = run_engine(["-i", folder, "-m", "waifu2x_cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    assert _resolved_levels(p.stderr) == [0, 0]
    outdir = workdir / "manga-(waifu2x_cunet)-n0-2.0x"
    assert outdir.is_dir()
    assert sorted(x.name for x in outdir.iterdir()) == ["a.png", "b.png"]


@needs_engine
def test_auto_folder_uniform_nonzero_level(workdir):
    """全批都是同一非零档 → 目录名写它，内部名不变"""
    folder = workdir / "dirty"
    folder.mkdir()
    for name in ("a", "b"):
        inp = folder / f"{name}.jpg"
        make_gradient(inp)
        Image.open(inp).save(inp, quality=10)  # 重压缩伪影

    p = run_engine(["-i", folder, "-m", "waifu2x_cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    levels = _resolved_levels(p.stderr)
    assert levels[0] == levels[1] and levels[0] > 0, levels
    outdir = workdir / f"dirty-(waifu2x_cunet)-n{levels[0]}-2.0x"
    assert outdir.is_dir()
    assert sorted(x.name for x in outdir.iterdir()) == ["a.png", "b.png"]


@needs_engine
def test_auto_folder_mixed_levels_mark_each_file(workdir):
    """工单 39：档位不一致 → 目录名 -nX-，每个文件各自补 -nN"""
    folder = workdir / "mixed"
    folder.mkdir()
    make_gradient(folder / "a.png")  # 干净 → 0
    inp = folder / "b.jpg"
    make_gradient(inp)
    Image.open(inp).save(inp, quality=10)  # 有伪影 → 非 0

    p = run_engine(["-i", folder, "-m", "waifu2x_cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    levels = _resolved_levels(p.stderr)
    assert len(levels) == 2 and levels[0] != levels[1], levels

    outdir = workdir / "mixed-(waifu2x_cunet)-nX-2.0x"
    assert outdir.is_dir()
    # 每个文件带上自己那次的解析档位（按处理顺序与 stderr 配对）
    expected = [f"{stem}-n{level}.png" for stem, level in zip(("a", "b"), levels)]
    assert sorted(x.name for x in outdir.iterdir()) == sorted(expected)
