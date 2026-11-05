"""添加后缀四态（`--suffix both|folder|file|none`）的参数契约

四态 × {文件夹输入, 单文件输入} 的命名矩阵断言在 test_naming.py；本文件只覆盖参数面：
四个取值都能用、`--no-rename` 与 `none` 同义、产物名跑前算不准时的运行期撞车拒绝。
"""
import pytest
from PIL import Image

from conftest import make_jpg, make_png, needs_engine, run_engine


@needs_engine
@pytest.mark.parametrize("value", ["both", "folder", "file", "none"])
def test_suffix_value_is_accepted(workdir, value):
    """四个取值都被参数解析接受：退出码 0，且写出一份本次超分结果"""
    inp = workdir / "A.png"
    make_png(inp)

    p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1", "--suffix", value])
    assert p.returncode == 0, (value, p.stderr)

    products = [x for x in workdir.iterdir() if x.suffix == ".jpg"]
    assert len(products) == 1, sorted(x.name for x in workdir.iterdir())
    assert Image.open(products[0]).size == (128, 128)


@needs_engine
def test_no_rename_is_synonym_of_suffix_none(workdir):
    """`--no-rename` 与 `--suffix none` 同义：产物路径与字节一致"""
    products = {}
    for tag, extra in (("no-rename", ["--no-rename"]), ("suffix-none", ["--suffix", "none"])):
        folder = workdir / tag
        folder.mkdir()
        inp = folder / "A.png"
        make_png(inp)
        p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1", *extra])
        assert p.returncode == 0, (tag, p.stderr)
        products[tag] = {x.name: x.read_bytes() for x in folder.iterdir()}

    assert products["no-rename"].keys() == products["suffix-none"].keys() == {"A.png", "A.jpg"}, products
    assert products["no-rename"] == products["suffix-none"]


@needs_engine
def test_suffix_file_target_mode_rejects_product_hitting_another_input(workdir):
    """开（文件）+ 目标尺寸：产物名跑前算不准，运行期仍须拒绝「产物撞同批另一输入」

    目录里 `a.png` 与 `a-(Resize)-32x.jpg` 同批：目标宽 32 < 原宽 64 → `a.png` 的产物正是
    后者（直通缩放的 -(Resize)-32x 段），它属于同批另一个输入 → 该文件按撞车失败（退出码 3），
    被撞的源图字节不变（静默覆盖会先毁掉一个未处理的源图）。
    """
    folder = workdir / "collide"
    folder.mkdir()
    make_png(folder / "a.png")
    victim = folder / "a-(Resize)-32x.jpg"
    make_jpg(victim)
    before = victim.read_bytes()

    p = run_engine(["-i", folder, "--width", "32", "-f", "jpg", "-g", "-1", "--suffix", "file"])
    assert p.returncode == 3, (p.returncode, p.stderr)
    assert "output path is another input file" in p.stderr, p.stderr
    assert victim.read_bytes() == before
