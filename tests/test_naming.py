"""命名规则与退出码（确定性断言）"""
import pytest
from PIL import Image

from conftest import MODEL, make_png, needs_engine, run_engine

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
