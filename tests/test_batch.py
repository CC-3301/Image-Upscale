"""工单 05：递归批处理（嵌套镜像、失败不中断、汇总）"""
import pytest
from PIL import Image

from conftest import make_png, needs_engine, run_engine


@needs_engine
def test_nested_folder_mirror_and_top_rename(workdir):
    # A/B/C/img.png + A/root.png：输出仅顶层重命名，B/C 原样镜像
    a = workdir / "A"
    c = a / "B" / "C"
    c.mkdir(parents=True)
    make_png(c / "img.png", size=(48, 32))
    make_png(a / "root.png", size=(48, 32))

    p = run_engine(["-i", a, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr

    out = workdir / "A-(waifu2x_upconv_7_art)-2.0x"
    assert out.is_dir()
    assert (out / "root.png").exists()
    assert (out / "B" / "C" / "img.png").exists()
    assert Image.open(out / "B" / "C" / "img.png").size == (96, 64)
    # 原目录不被修改
    assert (a / "B" / "C" / "img.png").exists()
    # 输出目录里不应出现第二层重命名（如 A-...-2.0x/B/A-...）
    assert not (out / "B" / "A-(waifu2x_upconv_7_art)-2.0x").exists()


@needs_engine
def test_corrupt_file_fails_but_batch_continues(workdir):
    folder = workdir / "batch"
    sub = folder / "sub"
    sub.mkdir(parents=True)
    make_png(folder / "good1.png", size=(48, 32))
    make_png(sub / "good2.png", size=(48, 32))
    # 损坏文件：后缀合法但内容非法 → 解码失败
    (folder / "bad.png").write_bytes(b"not a png at all")

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1"])
    assert p.returncode == 3  # IO/解码失败汇总

    out = workdir / "batch-(waifu2x_upconv_7_art)-2.0x"
    assert (out / "good1.png").exists()
    assert (out / "sub" / "good2.png").exists()
    assert not (out / "bad.png").exists()
    # 汇总报告
    assert "1 io failures" in p.stderr


@needs_engine
def test_progress_lines_match_files(workdir):
    folder = workdir / "multi"
    folder.mkdir()
    for i in range(3):
        make_png(folder / f"f{i}.png", size=(48, 32))
    p = run_engine(["-i", folder, "-f", "png", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    for i in range(1, 4):
        assert f"progress {i}/3" in p.stdout
    assert "done" in p.stdout
