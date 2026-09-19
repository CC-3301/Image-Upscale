"""工单 06：AUTO 降噪（伪影估计 → 档位映射）"""
import pytest
from PIL import Image

from conftest import make_gradient, make_png, needs_engine, resolved_levels, run_engine


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


@needs_engine
def test_auto_folder_uniform_level_folder_uses_it_and_keeps_names(workdir):
    """工单 39：全批档位一致 → 目录名写该档位，内部文件名原样镜像"""
    folder = workdir / "manga"
    folder.mkdir()
    make_gradient(folder / "a.png")  # 干净 → level 0
    make_gradient(folder / "b.png")
    p = run_engine(["-i", folder, "-m", "waifu2x_cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    assert resolved_levels(p.stderr) == [0, 0]
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
    levels = resolved_levels(p.stderr)
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
    levels = resolved_levels(p.stderr)
    assert len(levels) == 2 and levels[0] != levels[1], levels

    outdir = workdir / "mixed-(waifu2x_cunet)-nX-2.0x"
    assert outdir.is_dir()
    # 每个文件带上自己那次的解析档位（按处理顺序与 stderr 配对）
    expected = [f"{stem}-n{level}.png" for stem, level in zip(("a", "b"), levels)]
    assert sorted(x.name for x in outdir.iterdir()) == sorted(expected)


# ---- 工单 44/45 回归：AUTO 的档位完整性与批量权重重载 ----

@needs_engine
def test_auto_rejected_when_denoise_ladder_incomplete(workdir):
    """工单 44：AUTO 要求 无/低/中/高 四档齐备。

    realcugan-pro 只有 无/高：早期 AUTO 只检查「1/2/3 里存在任意一档」就放行，
    运行期按文件估计出 1/2 档后用它查清单（.at()）→ std::out_of_range → terminate。
    现在必须在参数校验阶段就以退出码 1 拒绝，且不得崩溃。
    """
    inp = workdir / "in.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-m", "realcugan-pro", "--denoise", "auto", "-f", "png", "-g", "-1"])
    assert p.returncode == 1, (p.returncode, p.stderr)
    assert "full denoise ladder" in p.stderr, p.stderr


@needs_engine
def test_auto_batch_zero_level_after_dirty_reloads_none_weights(workdir):
    """工单 45：批量 AUTO 中「非 0 档在前、0 档在后」必须重载权重。

    早期重载条件只比较倍数，而 AUTO 下 denoise_level 恒为 0，于是当前文件解析为 0 档时
    不触发重载 → 沿用上一个文件（脏图）的权重出图，命名却写 -n0。
    守卫方式：该 0 档产物必须与同一输入用 --denoise none 单跑出的产物逐位相同。
    """
    folder = workdir / "mixed"
    folder.mkdir()
    inp = folder / "a.jpg"
    make_gradient(inp)
    Image.open(inp).save(inp, quality=10)  # 脏图在前
    make_gradient(folder / "b.png")        # 干净图在后

    p = run_engine(["-i", folder, "-m", "waifu2x_cunet", "--denoise", "auto", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    levels = resolved_levels(p.stderr)
    # 顺序守卫：夹具必须保持「非 0 在前、0 在后」，否则本用例会空转通过
    assert len(levels) == 2 and levels[0] > 0 and levels[1] == 0, levels

    batch_out = workdir / "mixed-(waifu2x_cunet)-nX-2.0x" / "b-n0.png"
    assert batch_out.exists()

    single = run_engine(["-i", folder / "b.png", "-m", "waifu2x_cunet", "--denoise", "none",
                         "-f", "png", "-g", "-1"])
    assert single.returncode == 0, single.stderr
    # 单文件产物落在输入所在目录（single_file_outpath 用 in.parent_path()）
    ref = folder / "b-(waifu2x_cunet)-n0-2.0x.png"
    assert ref.exists(), sorted(x.name for x in folder.iterdir())

    assert Image.open(batch_out).tobytes() == Image.open(ref).tobytes()
