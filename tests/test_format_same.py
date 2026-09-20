"""工单 71：输出格式「与输入格式相同」（`-f same`）

口径（维护者 2026-09-20 定）：产物**扩展名保留输入的拼写**（`.jpeg` 就写 `.jpeg`，`.PNG` 就写 `.PNG`），
编码器按格式归一（jpeg/jpg → JPEG 编码）；文件夹输入时逐文件跟随自己的格式。
"""
import pytest
from PIL import Image

from conftest import MODEL, make_jpg, make_png, make_webp, needs_engine, run_engine

MODEL_TAG = f"({MODEL})"

# 输入名 → (夹具 helper, PIL 读回的 format)
FIXTURES = {
    "A.png": (make_png, "PNG"),
    "A.jpg": (make_jpg, "JPEG"),
    "A.jpeg": (make_jpg, "JPEG"),
    "A.webp": (make_webp, "WEBP"),
}


@needs_engine
@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_same_follows_input_format_and_keeps_extension_spelling(workdir, name):
    """单文件 + `-f same`：产物扩展名 = 输入扩展名原样，编码格式与之匹配"""
    make, expected_format = FIXTURES[name]
    inp = workdir / name
    make(inp)

    p = run_engine(["-i", inp, "-f", "same", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    ext = name.split(".", 1)[1]
    # 比真实文件名（大小写敏感）：NTFS 不区分大小写，只 exists() 会漏掉拼写没保留的回归
    assert {x.name for x in workdir.iterdir()} == {name, f"A-{MODEL_TAG}-n0-2.0x.{ext}"}
    img = Image.open(workdir / f"A-{MODEL_TAG}-n0-2.0x.{ext}")
    assert img.format == expected_format
    assert img.size == (128, 128)


@needs_engine
def test_same_keeps_alpha_for_png_input(workdir):
    """「与输入格式相同」+ RGBA PNG：产物仍是 RGBA

    alpha 分支（engine 里 `c == 4 && 本文件编码器 != jpg`）必须用**本文件**的编码器 ——
    退回整批 opt.format 时会静默丢透明而用例仍绿（lessons §3.2：夹具要盖住被守护的维度）。
    """
    inp = workdir / "A.png"
    make_png(inp, mode="RGBA")

    p = run_engine(["-i", inp, "-f", "same", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    out = workdir / f"A-{MODEL_TAG}-n0-2.0x.png"
    assert Image.open(out).mode == "RGBA"


@needs_engine
def test_same_uppercase_extension_keeps_spelling(workdir):
    """扩展名大小写也保留（`A.PNG` → 产物 `.PNG`）——「保留输入的拼写」的字面口径"""
    inp = workdir / "A.PNG"
    make_png(inp)

    p = run_engine(["-i", inp, "-f", "same", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    # 必须比**盘上的真实文件名**：NTFS 大小写不敏感，用 ".PNG" 拼路径去 exists() 是空断言
    assert {x.name for x in workdir.iterdir()} == {"A.PNG", f"A-{MODEL_TAG}-n0-2.0x.PNG"}
    assert Image.open(workdir / f"A-{MODEL_TAG}-n0-2.0x.PNG").format == "PNG"


@needs_engine
def test_same_folder_keeps_each_files_format(workdir):
    """文件夹 + `-f same`：每个产物跟随自己那份输入的格式（混合格式目录一次跑完）"""
    folder = workdir / "mix"
    folder.mkdir()
    make_png(folder / "a.png")
    make_jpg(folder / "b.jpg")
    make_webp(folder / "c.webp")

    p = run_engine(["-i", folder, "-f", "same", "-g", "-1"])
    assert p.returncode == 0, p.stderr

    outdir = workdir / f"mix-{MODEL_TAG}-n0-2.0x"
    expected = {"a.png": "PNG", "b.jpg": "JPEG", "c.webp": "WEBP"}
    assert sorted(x.name for x in outdir.iterdir()) == sorted(expected)
    for fname, fmt in expected.items():
        assert Image.open(outdir / fname).format == fmt


@needs_engine
def test_same_folder_allows_same_stem_different_extension(workdir):
    """文件夹 + `-f same` + 同 stem 不同扩展名：产物扩展名不同 → **不撞车**，两个都能跑完

    对比：同一目录配 `-f jpg` 会被跑前守卫拒绝（工单 70，见 test_naming.py 的同名用例）。
    """
    folder = workdir / "same-stem"
    folder.mkdir()
    make_png(folder / "1.png", size=(32, 32))
    make_jpg(folder / "1.jpg", size=(32, 32))

    p = run_engine(["-i", folder, "-f", "same", "-g", "-1"])
    assert p.returncode == 0, p.stderr
    outdir = workdir / f"same-stem-{MODEL_TAG}-n0-2.0x"
    assert sorted(x.name for x in outdir.iterdir()) == ["1.jpg", "1.png"]
    assert Image.open(outdir / "1.jpg").format == "JPEG"
    assert Image.open(outdir / "1.png").format == "PNG"


@needs_engine
def test_same_with_no_rename_overwrites_each_source_in_place(workdir):
    """关后缀段 + `-f same` + 文件夹：产物名与源名完全一致 → 整树原地超分，不新增文件

    这是「与输入格式相同」+「添加扩展名关」的自然组合：`1.jpg` 还是 `1.jpg`、`1.png` 还是 `1.png`。
    """
    folder = workdir / "inplace"
    folder.mkdir()
    make_png(folder / "1.png", size=(32, 32))
    make_jpg(folder / "1.jpg", size=(32, 32))
    jpg_before = (folder / "1.jpg").read_bytes()

    p = run_engine(["-i", folder, "-f", "same", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, p.stderr
    assert sorted(x.name for x in folder.iterdir()) == ["1.jpg", "1.png"]
    assert Image.open(folder / "1.png").size == (64, 64)   # PNG 被自己的产物原地替换
    assert Image.open(folder / "1.jpg").size == (64, 64)   # JPG 同理
    assert (folder / "1.jpg").read_bytes() != jpg_before   # 确实被重写了（不是原文件原封不动）
