"""命名规则与退出码（确定性断言）"""
import pytest
from PIL import Image

from conftest import MODEL, make_gradient, make_png, needs_engine, resolved_levels, run_engine

MODEL_TAG = f"({MODEL})"


@needs_engine
def test_single_file_default_jpg_naming(workdir):
    inp = workdir / "photo.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"photo-{MODEL_TAG}-n0-2.0x.jpg"
    assert out.exists()
    assert Image.open(out).size == (128, 128)


@needs_engine
def test_single_file_explicit_png_format(workdir):
    inp = workdir / "A.webp"
    make_png(inp)  # 内容是 png 但后缀 .webp 是错的；改为真 webp
    inp.unlink()
    # 用 Pillow 生成真 webp
    make_png(workdir / "A.tmp.png")
    Image.open(workdir / "A.tmp.png").save(inp, format="WEBP")
    (workdir / "A.tmp.png").unlink()

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"A-{MODEL_TAG}-n0-2.0x.png"
    assert out.exists()
    with open(out, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"


@needs_engine
def test_folder_input_sibling_folder_naming(workdir):
    folder = workdir / "manga"
    folder.mkdir()
    make_png(folder / "p001.png")
    make_png(folder / "p002.png")

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr

    outdir = workdir / f"manga-{MODEL_TAG}-n0-2.0x"
    assert outdir.is_dir()
    assert (outdir / "p001.png").exists()
    assert (outdir / "p002.png").exists()
    # 顶层无匹配图片文件不进入输出
    assert sorted(x.name for x in outdir.iterdir()) == ["p001.png", "p002.png"]


@needs_engine
def test_folder_skips_non_image_files(workdir):
    folder = workdir / "sk"
    folder.mkdir()
    make_png(folder / "a.png")
    (folder / "readme.txt").write_text("hello", encoding="utf-8")
    p = run_engine(["-i", folder, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    outdir = workdir / f"sk-{MODEL_TAG}-n0-2.0x"
    assert (outdir / "a.png").exists()
    assert not (outdir / "readme.txt").exists()


@needs_engine
def test_overwrite_on_rerun(workdir):
    inp = workdir / "A.png"
    make_png(inp)
    p1 = run_engine(["-i", inp, "-f", "png", "-g", "-1"])
    assert p1.returncode == 0
    out = workdir / f"A-{MODEL_TAG}-n0-2.0x.png"
    first = out.read_bytes()
    p2 = run_engine(["-i", inp, "-f", "png", "-g", "-1"])
    assert p2.returncode == 0
    assert out.read_bytes() == first  # 覆盖且结果一致


@needs_engine
def test_progress_lines_on_stdout(workdir):
    inp = workdir / "A.png"
    make_png(inp)
    p = run_engine(["-i", inp, "-g", "-1"])
    assert p.returncode == 0
    assert "progress 1/1" in p.stdout
    assert "done" in p.stdout


# ---- 工单 50：关闭后缀段（--no-rename，只作用于文件输入）----

@needs_engine
def test_no_rename_file_input_uses_original_name(workdir):
    """文件输入 + --no-rename：产物 = 源文件同目录 + 原文件名 + 输出格式扩展名（无任何后缀段）"""
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.png"
    make_png(inp)

    p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, p.stderr
    assert (folder / "A.jpg").exists()
    # 目录内只有源图与产物：没有带 -(模型名)-nN-<倍率> 段的第二个产物
    assert sorted(x.name for x in folder.iterdir()) == ["A.jpg", "A.png"]


@needs_engine
def test_no_rename_direct_resize_omits_resize_segment(workdir):
    """直通缩放（目标 < 原图）同样不加 -(Resize)-<尺寸> 段"""
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.png"
    make_png(inp)  # 64x64

    p = run_engine(["-i", inp, "--width", "32", "-f", "jpg", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, p.stderr
    assert (folder / "A.jpg").exists()
    assert sorted(x.name for x in folder.iterdir()) == ["A.jpg", "A.png"]
    assert Image.open(folder / "A.jpg").size == (32, 32)


@needs_engine
def test_no_rename_same_output_format_refuses_overwrite(workdir):
    """守卫：产物路径与输入路径相同（A.png + -f png）时必须拒绝写盘，源图原封不动"""
    inp = workdir / "A.png"
    make_png(inp)
    before = inp.read_bytes()

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1", "--no-rename"])
    assert p.returncode == 3, (p.returncode, p.stderr)
    assert "refuse to overwrite input" in p.stderr, p.stderr
    assert inp.read_bytes() == before
    assert sorted(x.name for x in workdir.iterdir()) == ["A.png"]
    assert " done" not in p.stdout


@needs_engine
def test_no_rename_same_format_uppercase_extension_refuses_overwrite(workdir):
    """扩展名大小写不同也指向同一个文件（Windows 不区分大小写），同样拒绝写盘"""
    inp = workdir / "A.PNG"
    make_png(inp)
    before = inp.read_bytes()

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1", "--no-rename"])
    assert p.returncode == 3, (p.returncode, p.stderr)
    assert "refuse to overwrite input" in p.stderr, p.stderr
    assert inp.read_bytes() == before
    assert sorted(x.name for x in workdir.iterdir()) == ["A.PNG"]


@needs_engine
def test_no_rename_ignored_for_folder_input(workdir):
    """开关只作用于文件输入：目录输入仍输出到 B-(模型名)-nN-<倍率>/ 且内部名原样镜像"""
    folder = workdir / "B"
    folder.mkdir()
    make_png(folder / "p001.png")

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, p.stderr

    outdir = workdir / f"B-{MODEL_TAG}-n0-2.0x"
    assert outdir.is_dir()
    assert (outdir / "p001.png").exists()
    # 源目录未被写入（开关在目录模式下不生效）
    assert sorted(x.name for x in folder.iterdir()) == ["p001.png"]


@needs_engine
def test_no_rename_keeps_auto_mixed_level_segments(workdir):
    """目录 + --no-rename + AUTO 档位不一致：目录名仍写 nX，内部仍各补 -nN（工单 39 不回归）"""
    folder = workdir / "mixed"
    folder.mkdir()
    make_gradient(folder / "a.png")  # 干净 → 0 档
    dirty = folder / "b.jpg"
    make_gradient(dirty)
    Image.open(dirty).save(dirty, quality=10)  # 重压缩伪影 → 非 0 档

    p = run_engine(["-i", folder, "-m", "waifu2x_cunet", "--denoise", "auto",
                    "-f", "png", "-g", "-1", "-v", "--no-rename"])
    assert p.returncode == 0, p.stderr
    levels = resolved_levels(p.stderr)
    # 顺序守卫：夹具必须保持档位不一致，否则本用例会空转通过
    assert len(levels) == 2 and levels[0] != levels[1], levels

    outdir = workdir / "mixed-(waifu2x_cunet)-nX-2.0x"
    assert outdir.is_dir()
    expected = [f"{stem}-n{level}.png" for stem, level in zip(("a", "b"), levels)]
    assert sorted(x.name for x in outdir.iterdir()) == sorted(expected)


@needs_engine
def test_no_rename_same_format_cyrillic_case_variant_refuses_overwrite(workdir):
    """非 ASCII 大小写变体（西里尔 А / а）也指向同一个文件：NTFS 上 А.PNG 与 А.png 同路径。

    守卫的大小写折叠若跟着进程 locale 走（towlower + setlocale(LC_ALL,"")），非 ASCII
    大小写映射就不可靠 → 漏检即写回源图。折叠改走序号比较（CompareStringOrdinal）后与 locale 无关。
    """
    on_disk = workdir / "А.PNG"  # 西里尔大写 А + 大写扩展名
    make_png(on_disk)
    # 两种拼写（大写 / 小写西里尔，小写扩展名）都在 NTFS 上解析到同一个文件
    for typed in ("А.PNG", "а.png"):
        before = on_disk.read_bytes()
        p = run_engine(["-i", workdir / typed, "-f", "png", "-g", "-1", "--no-rename"])
        assert p.returncode == 3, (typed, p.returncode, p.stderr)
        assert "refuse to overwrite input" in p.stderr, p.stderr
        assert on_disk.read_bytes() == before
    assert sorted(x.name for x in workdir.iterdir()) == ["А.PNG"]
