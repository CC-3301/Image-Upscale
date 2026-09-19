"""命名规则与退出码（确定性断言）"""
import pytest
from PIL import Image

from conftest import MODEL, make_gradient, make_png, needs_engine, psnr, resolved_levels, run_engine

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
    before = inp.read_bytes()

    p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, p.stderr
    assert (folder / "A.jpg").exists()
    # 目录内只有源图与产物：没有带 -(模型名)-nN-<倍率> 段的第二个产物
    assert sorted(x.name for x in folder.iterdir()) == ["A.jpg", "A.png"]
    # 异格式产物落到新文件：源图字节不变（工单 58 只改了同格式这一条）
    assert inp.read_bytes() == before


@needs_engine
def test_no_rename_jpeg_extension_sibling_is_not_same_path(workdir):
    """`.jpeg` + `-f jpg`：扩展名代理（jpeg↔jpg）不是同一个文件 → 不命中原地覆盖

    守护文档承诺的边界（spec.md 命名规则段/冲突策略段、README、CONTEXT）：产物 = stem + "." + 输出
    扩展名 = `A.jpg` ≠ 输入 `A.jpeg` → 新增 `A.jpg`、源图字节不变（误判为同一文件会覆盖源图，不可撤销）。
    """
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.jpeg"
    make_png(folder / "A.tmp.png", size=(32, 32))
    Image.open(folder / "A.tmp.png").save(inp, format="JPEG", quality=90)
    (folder / "A.tmp.png").unlink()
    before = inp.read_bytes()

    p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, (p.returncode, p.stderr)
    # 不命中：产物是新文件，源图原封不动
    assert sorted(x.name for x in folder.iterdir()) == ["A.jpeg", "A.jpg"]
    assert inp.read_bytes() == before
    assert Image.open(folder / "A.jpg").size == (64, 64)


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


# ---- 工单 58：关后缀段 + 输出格式与输入相同 → 原地覆盖源文件 ----

def _reference_product(workdir, src):
    """同源图带后缀段跑一次 → 参考产物（断言原地覆盖的「内容是超分结果」时作对比基准）"""
    refdir = workdir / "ref"
    refdir.mkdir(exist_ok=True)
    refsrc = refdir / src.name
    refsrc.write_bytes(src.read_bytes())
    p = run_engine(["-i", refsrc, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = refdir / f"{refsrc.stem}-{MODEL_TAG}-n0-2.0x.png"
    assert out.exists(), sorted(x.name for x in refdir.iterdir())
    return out


@needs_engine
def test_no_rename_same_output_format_overwrites_source_in_place(workdir):
    """关后缀段 + 输出格式与输入相同（工单 58）：目标路径即输入路径 → 原地覆盖源文件

    夹具 32×32 经 2x 模型得 64×64。尺寸只证明「源文件被替换」，内容才算证明「替换成的是超分结果」
    （同尺寸坏图会全绿），故与同源图的参考产物比 PSNR：实测 99.0 dB（像素级一致），阈值取 40。
    """
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.png"
    make_png(inp, size=(32, 32))
    ref = _reference_product(workdir, inp)

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, (p.returncode, p.stderr)
    assert " done" in p.stdout, p.stdout
    # 目录内不新增文件：产物就是源文件本身
    assert sorted(x.name for x in folder.iterdir()) == ["A.png"]
    img = Image.open(inp)
    assert img.format == "PNG"
    assert img.size == (64, 64)
    assert psnr(img, Image.open(ref)) >= 40.0


@needs_engine
def test_no_rename_same_format_uppercase_extension_overwrites_in_place(workdir):
    """扩展名大小写不同也指向同一个文件（Windows 不区分大小写），同样原地覆盖、不新增文件"""
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.PNG"
    make_png(inp, size=(32, 32))
    ref = _reference_product(workdir, inp)

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, (p.returncode, p.stderr)
    # 覆盖写盘不会改动盘上已有的文件名拼写
    assert sorted(x.name for x in folder.iterdir()) == ["A.PNG"]
    assert Image.open(inp).size == (64, 64)
    assert psnr(Image.open(inp), Image.open(ref)) >= 40.0  # 实测 99.0


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
def test_no_rename_cyrillic_case_variant_overwrites_in_place(workdir):
    """非 ASCII 文件名 + 两种拼写变体（NTFS 上同一个文件）→ 均原地覆盖，不新增文件。

    两轮各放大 2 倍（32 → 64 → 128）：只有两种拼写都写到同一个文件才会得到 128×128；
    若任一拼写新建了文件，目录内会多出第二个文件，断言随之失败。
    第一轮即与参考产物比 PSNR：内容确为超分结果（实测 99.0 dB），而非同尺寸的别的图。
    """
    folder = workdir / "B"
    folder.mkdir()
    on_disk = folder / "А.PNG"  # 西里尔大写 А + 大写扩展名
    make_png(on_disk, size=(32, 32))
    before = on_disk.read_bytes()
    ref = _reference_product(workdir, on_disk)

    # 两种拼写（大写 / 小写西里尔，小写扩展名）都在 NTFS 上解析到同一个文件
    p1 = run_engine(["-i", folder / "А.PNG", "-f", "png", "-g", "-1", "--no-rename"])
    assert p1.returncode == 0, (p1.returncode, p1.stderr)
    first = Image.open(on_disk).copy()  # 先脱离文件句柄：下一轮要原地重写同一路径
    assert first.size == (64, 64)
    assert psnr(first, Image.open(ref)) >= 40.0

    p2 = run_engine(["-i", folder / "а.png", "-f", "png", "-g", "-1", "--no-rename"])
    assert p2.returncode == 0, (p2.returncode, p2.stderr)
    assert on_disk.read_bytes() != before
    assert Image.open(on_disk).size == (128, 128)
    assert sorted(x.name for x in folder.iterdir()) == ["А.PNG"]
