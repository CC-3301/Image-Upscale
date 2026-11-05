"""序列化重命名（`--sequence`）：产物名主干换成按自然序发的编号

判据全部落在文件系统上（引擎 CLI 是唯一测试缝）：产物名集合、产物尺寸（用尺寸反推编号顺序）、
源文件名是否还在、退出码、stderr 文案。GUI 侧开关与 setting.ini 无自动化测试（人工验收）。
"""
import pytest
from PIL import Image

from conftest import MODEL, make_jpg, make_png, needs_engine, run_engine

MODEL_TAG = f"({MODEL})"


@needs_engine
def test_folder_numbers_products_in_natural_order(workdir):
    """文件夹输入：产物按现有文件名的自然序编号为 001/002/003，数字按大小而不是按字面

    `1.png`(40px) / `2.png`(32px) / `10.png`(48px) 的自然序是 1 → 2 → 10（字面序则是
    1 → 10 → 2）。产物尺寸 = 原尺寸 ×2，据此反推每个编号拿到的是哪张图。
    """
    folder = workdir / "seq"
    folder.mkdir()
    make_png(folder / "2.png", size=(32, 32))
    make_png(folder / "1.png", size=(40, 40))
    make_png(folder / "10.png", size=(48, 48))

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1", "--sequence"])
    assert p.returncode == 0, p.stderr

    outdir = workdir / f"seq-{MODEL_TAG}-n0-2.0x"
    assert sorted(x.name for x in outdir.iterdir()) == ["001.png", "002.png", "003.png"]
    assert Image.open(outdir / "001.png").size == (80, 80)   # 1.png
    assert Image.open(outdir / "002.png").size == (64, 64)   # 2.png
    assert Image.open(outdir / "003.png").size == (96, 96)   # 10.png


@needs_engine
def test_natural_order_ignores_letter_case(workdir):
    """字母不分大小写：`a.png` 排在 `B.png` 前（字面序会把大写 B 排在前）"""
    folder = workdir / "case"
    folder.mkdir()
    make_png(folder / "B.png", size=(40, 40))
    make_png(folder / "a.png", size=(32, 32))

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1", "--sequence", "--suffix", "none"])
    assert p.returncode == 0, p.stderr
    assert Image.open(folder / "001.png").size == (64, 64)   # a.png
    assert Image.open(folder / "002.png").size == (80, 80)   # B.png


@needs_engine
def test_each_folder_numbers_from_001(workdir):
    """每个子文件夹各自从 001 起，子文件夹本身不改名，源文件名不变"""
    folder = workdir / "tree"
    (folder / "inner").mkdir(parents=True)
    make_png(folder / "a.png")
    make_png(folder / "b.png")
    make_png(folder / "inner" / "c.png")
    make_png(folder / "inner" / "d.png")
    sources = {p.relative_to(folder).as_posix() for p in folder.rglob("*.png")}

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1", "--sequence", "--suffix", "none"])
    assert p.returncode == 0, p.stderr

    assert sorted(x.name for x in folder.iterdir()) == ["001.png", "002.png", "a.png", "b.png", "inner"]
    assert sorted(x.name for x in (folder / "inner").iterdir()) == ["001.png", "002.png", "c.png", "d.png"]
    # 源文件名全程不变（源图都还在，只是多了产物）
    assert sources <= {p.relative_to(folder).as_posix() for p in folder.rglob("*.png")}


@needs_engine
def test_single_file_input_is_numbered_001(workdir):
    """单文件输入的产物编号就是 001（本目录只有它自己）"""
    inp = workdir / "photo.png"
    make_png(inp)

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1", "--sequence"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"001-{MODEL_TAG}-n0-2.0x.png"
    assert out.exists()
    assert Image.open(out).size == (128, 128)
    assert inp.exists()


@needs_engine
def test_non_image_files_keep_their_names(workdir):
    """只有 jpg/jpeg/png/webp 参与编号，其它文件一个字节不动"""
    folder = workdir / "mix"
    folder.mkdir()
    make_png(folder / "a.png")
    note = folder / "readme.txt"
    note.write_text("hello", encoding="utf-8")
    other = folder / "anim.gif"
    other.write_bytes(b"GIF89a")

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1", "--sequence", "--suffix", "none"])
    assert p.returncode == 0, p.stderr
    assert sorted(x.name for x in folder.iterdir()) == ["001.png", "a.png", "anim.gif", "readme.txt"]
    assert note.read_text(encoding="utf-8") == "hello"
    assert other.read_bytes() == b"GIF89a"


@needs_engine
@pytest.mark.parametrize("suffix", ["both", "folder", "file", "none"])
def test_sequence_stacks_with_suffix_modes(workdir, suffix):
    """编号与「添加后缀」四态叠加：段的位置由四态决定，产物名主干恒为编号"""
    folder = workdir / "src"
    folder.mkdir()
    make_png(folder / "a.png")

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1", "--sequence", "--suffix", suffix])
    assert p.returncode == 0, p.stderr

    if suffix in ("both", "folder"):
        # 段在输出文件夹名上，产物文件名干净
        path = workdir / f"src-{MODEL_TAG}-n0-2.0x" / "001.png"
    elif suffix == "file":
        # 不建输出目录，整段带在产物文件名上
        path = folder / f"001-{MODEL_TAG}-n0-2.0x.png"
    else:
        path = folder / "001.png"
    assert path.exists(), sorted(str(x) for x in workdir.rglob("*.png"))
    assert Image.open(path).size == (128, 128)


@needs_engine
def test_sequence_pads_to_three_digits_and_grows_past_999(workdir):
    """3 位补零；文件数超过 999 时自然变 4 位（1000 张 → 最后一个是 1000.png）"""
    folder = workdir / "many"
    folder.mkdir()
    for i in range(1, 1001):
        make_png(folder / f"p{i:04d}.png", size=(16, 16))

    # 目标尺寸小于原图 → 直通缩放，不跑模型（本用例只验编号面）
    p = run_engine(["-i", folder, "--width", "8", "-f", "png", "-g", "-1", "--sequence", "--suffix", "none"])
    assert p.returncode == 0, p.stderr

    names = {x.name for x in folder.iterdir() if x.suffix == ".png" and x.name[0].isdigit()}
    assert len(names) == 1000, len(names)
    assert {"001.png", "002.png", "003.png", "999.png", "1000.png"} <= names
    assert "0001.png" not in names  # 超过 999 才变 4 位，不是一律 4 位


@needs_engine
def test_output_goes_through_a_temp_file_then_rename(workdir):
    """产物先写同目录临时文件、再改名成目标：改名失败时目标不被写坏，现场只剩临时文件

    造法：目标路径已被一个**目录**占用（改名到目录必然失败）。退出码 3、目标仍是目录、
    只留下 `001.png.iu-tmp`（若改成直接写目标，这里会是一个半截图文件或被写成目录里的图片）。
    """
    folder = workdir / "tmpw"
    folder.mkdir()
    make_png(folder / "a.png")
    (folder / "001.png").mkdir()

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1", "--sequence", "--suffix", "none"])
    assert p.returncode == 3, (p.returncode, p.stderr)
    assert "cannot write output" in p.stderr, p.stderr
    assert (folder / "001.png").is_dir()
    assert (folder / "001.png.iu-tmp").is_file()
    assert folder.joinpath("a.png").exists()


@needs_engine
def test_sequence_with_delete_input_keeps_product_and_drops_source(workdir):
    """序列化重命名 + 删除输入文件：产物 001.jpg 留下，源图 a.png 消失（删源在改名成功之后）"""
    folder = workdir / "conv"
    folder.mkdir()
    make_png(folder / "a.png")

    p = run_engine(["-i", folder, "-f", "jpg", "-g", "-1", "--sequence", "--suffix", "none", "--delete-input"])
    assert p.returncode == 0, p.stderr
    assert sorted(x.name for x in folder.iterdir()) == ["001.jpg"]
    assert Image.open(folder / "001.jpg").size == (128, 128)
    assert not list(folder.glob("*.iu-tmp"))  # 改名成功后不留临时文件


@needs_engine
def test_collision_guard_still_rejects_when_both_switches_are_off(workdir):
    """两个开关都关：跑前撞车守卫照旧生效（退出码 1、不写出任何产物）"""
    folder = workdir / "guard"
    folder.mkdir()
    make_png(folder / "a.png", size=(32, 32))
    make_jpg(folder / "a.jpg", size=(32, 32))
    before = {p.name: p.read_bytes() for p in folder.iterdir()}

    p = run_engine(["-i", folder, "-f", "jpg", "-g", "-1", "--suffix", "none"])
    assert p.returncode == 1, (p.returncode, p.stderr)
    assert "would overwrite another input file" in p.stderr, p.stderr
    assert {q.name: q.read_bytes() for q in folder.iterdir()} == before


@needs_engine
def test_collision_guard_is_off_when_delete_input_is_on(workdir):
    """任一开关打开（这里是「删除输入文件」）：同样的输入一律覆盖、不报错"""
    folder = workdir / "guard-del"
    folder.mkdir()
    make_png(folder / "a.png", size=(32, 32))
    make_jpg(folder / "a.jpg", size=(32, 32))

    p = run_engine(["-i", folder, "-f", "jpg", "-g", "-1", "--suffix", "none", "--delete-input"])
    assert p.returncode == 0, p.stderr
    assert "would overwrite another input file" not in p.stderr
    # a.jpg 先按自己的产物原地覆盖，随后 a.png 的产物盖掉它并删掉 a.png
    assert sorted(x.name for x in folder.iterdir()) == ["a.jpg"]
    assert Image.open(folder / "a.jpg").size == (64, 64)


@needs_engine
def test_collision_guard_is_off_when_sequence_is_on(workdir):
    """任一开关打开（这里是「序列化重命名」）：同样的输入不报错，产物按编号写出"""
    folder = workdir / "guard-seq"
    folder.mkdir()
    make_png(folder / "a.png", size=(32, 32))
    make_jpg(folder / "a.jpg", size=(32, 32))

    p = run_engine(["-i", folder, "-f", "jpg", "-g", "-1", "--suffix", "none", "--sequence"])
    assert p.returncode == 0, p.stderr
    assert "would overwrite another input file" not in p.stderr
    assert sorted(x.name for x in folder.iterdir()) == ["001.jpg", "002.jpg", "a.jpg", "a.png"]


@needs_engine
def test_help_documents_sequence_flag():
    """`--help` 有 `--sequence` 的说明"""
    p = run_engine(["-h"])
    assert p.returncode == 0, p.stderr
    assert "--sequence" in p.stdout
