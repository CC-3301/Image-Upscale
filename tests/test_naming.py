"""命名规则与退出码（确定性断言）"""
import pytest
from PIL import Image

from conftest import (MODEL, auto_levels_by_file, make_gradient, make_jpg, make_png, make_webp, needs_engine,
                      psnr, run_engine)

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
    make_webp(inp)  # 真 webp 输入（显式 format="WEBP" 编码）

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


# ---- 工单 50/68：关闭后缀段（--no-rename）—— 工单 68 起对文件与文件夹输入都生效 ----

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
    make_jpg(inp, size=(32, 32))  # 真 JPEG：用 conftest 的夹具 helper
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

def _reference_product(workdir, src, args=()):
    """同源图带后缀段跑一次 → 参考产物（断言原地覆盖的「内容是超分结果」时作对比基准）

    args：参考跑额外参数（直通缩放需带 --width/--height）。产物名随走 SR 还是直通缩放分支而不同，
    这里只认 refdir 里「除源图副本之外多出的那一个」，不重复铺命名规则（命名由其它用例断言）。
    """
    refdir = workdir / "ref"
    refdir.mkdir(exist_ok=True)
    refsrc = refdir / src.name
    refsrc.write_bytes(src.read_bytes())
    p = run_engine(["-i", refsrc, "-f", "png", "-g", "-1", *args])
    assert p.returncode == 0, p.stderr
    products = [x for x in refdir.iterdir() if x != refsrc]
    assert len(products) == 1, sorted(x.name for x in refdir.iterdir())
    return products[0]


def _run_in_place(workdir, name, size=(32, 32), args=()):
    """B/<name>（默认 32×32 夹具）备好参考产物后原地跑一轮 `--no-rename`。

    size：夹具尺寸；args：参考跑与原地跑共用的额外参数（直通缩放传 --width）。
    返回 (目录, 源文件, 参考产物, 引擎结果, 跑前源图字节)。
    """
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / name
    make_png(inp, size=size)
    before = inp.read_bytes()
    ref = _reference_product(workdir, inp, args=args)
    p = run_engine(["-i", inp, "-f", "png", "-g", "-1", *args, "--no-rename"])
    return folder, inp, ref, p, before


def _assert_in_place_product(inp, ref, size):
    """原地覆盖的共同判据：产物 = 真 PNG + 目标尺寸 + 内容确是本次处理结果（与参考产物比 PSNR）

    只承载四条用例共有的四项断言（打开 / format / size / PSNR）；跑几轮、扩展名拼写、
    非 ASCII、--width 各例自持。
    """
    img = Image.open(inp)
    assert img.format == "PNG"
    assert img.size == size
    assert psnr(img, Image.open(ref)) >= 40.0


@needs_engine
def test_no_rename_same_output_format_overwrites_source_in_place(workdir):
    """关后缀段 + 输出格式与输入相同（工单 58）：目标路径即输入路径 → 原地覆盖源文件

    夹具 32×32 经 2x 模型得 64×64。尺寸只证明「源文件被替换」，内容才算证明「替换成的是超分结果」
    （同尺寸坏图会全绿），故与同源图的参考产物比 PSNR：实测 99.0 dB（像素级一致），阈值取 40。
    """
    folder, inp, ref, p, _ = _run_in_place(workdir, "A.png")

    assert p.returncode == 0, (p.returncode, p.stderr)
    assert " done" in p.stdout, p.stdout
    # 目录内不新增文件：产物就是源文件本身
    assert sorted(x.name for x in folder.iterdir()) == ["A.png"]
    _assert_in_place_product(inp, ref, size=(64, 64))


@needs_engine
def test_no_rename_same_format_uppercase_extension_overwrites_in_place(workdir):
    """扩展名大小写不同也指向同一个文件（Windows 不区分大小写），同样原地覆盖、不新增文件"""
    folder, inp, ref, p, _ = _run_in_place(workdir, "A.PNG")

    assert p.returncode == 0, (p.returncode, p.stderr)
    # 覆盖写盘不会改动盘上已有的文件名拼写
    assert sorted(x.name for x in folder.iterdir()) == ["A.PNG"]
    _assert_in_place_product(inp, ref, size=(64, 64))  # PSNR 实测 99.0


@needs_engine
def test_no_rename_folder_input_writes_next_to_sources(workdir):
    """工单 68：关后缀段对目录输入同样生效 —— 产物 = 源文件同目录 + 原文件名 + 输出格式扩展名，
    不再另建 B-(模型名)-nN-<倍率>/ 输出目录（撤销工单 50 定案 1 的「目录模式忽略该开关」）"""
    folder = workdir / "B"
    folder.mkdir()
    make_png(folder / "p001.png")

    p = run_engine(["-i", folder, "-f", "jpg", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, p.stderr
    assert (folder / "p001.jpg").exists()
    assert not (workdir / f"B-{MODEL_TAG}-n0-2.0x").exists()
    # 异格式：源图仍在且字节不变
    assert Image.open(folder / "p001.png").size == (64, 64)
    assert sorted(x.name for x in folder.iterdir()) == ["p001.jpg", "p001.png"]


@needs_engine
def test_no_rename_folder_input_keeps_subdirectory_layout(workdir):
    """关后缀段 + 递归目录：子目录结构原样保留（产物落在各自原位置，不摊平到一层）"""
    folder = workdir / "sub"
    (folder / "inner").mkdir(parents=True)
    make_png(folder / "a.png")
    make_png(folder / "inner" / "b.png")

    p = run_engine(["-i", folder, "-f", "jpg", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, p.stderr
    assert (folder / "a.jpg").exists()
    assert (folder / "inner" / "b.jpg").exists()
    assert not (workdir / f"sub-{MODEL_TAG}-n0-2.0x").exists()


@needs_engine
def test_no_rename_folder_rejects_colliding_outputs(workdir):
    """工单 68（评审 P1）：关后缀段 + 目录里产物撞车 → 跑之前就拒绝（退出码 1），源图一个字节都不许动。

    两种撞法都要拒（② 是 r2 评审补的：r1 的守卫只索引输入，盖不住产物之间撞车）：
      ① 产物撞上**同批的另一个输入文件**：a.png + a.jpg 配 -f jpg（a.png 的产物就是 a.jpg）/ -f png；
      ② 两个产物彼此同路：a.png + a.jpg 配 -f webp（都产出 a.webp）/ a.png + a.jpeg 配 -f jpg（两个 stem 都是 a）。

    修复前的静默后果（bld 实测，NTFS 遍历顺序 a.jpg 在前）：a.jpg 先被自己的产物原地覆盖，
    随后 a.png 的产物又把 a.jpg 盖掉 → 原 a.jpg 从未被处理就消失，退出码却是 0；
    顺序反过来则是 a.jpg 读到 a.png 刚写出的产物 → 同一张图被放大两轮。
    """
    folder = workdir / "collide"
    folder.mkdir()
    make_png(folder / "a.png", size=(32, 32))
    make_jpg(folder / "a.jpg", size=(32, 32))
    before = {p.name: p.read_bytes() for p in folder.iterdir()}

    # ① 产物撞输入：jpg 撞 a.jpg 本身、png 撞 a.png 本身
    for fmt in ("jpg", "png"):
        p = run_engine(["-i", folder, "-f", fmt, "-g", "-1", "--no-rename"])
        assert p.returncode == 1, (fmt, p.returncode, p.stderr)
        assert "would overwrite another input file" in p.stderr, p.stderr
        assert {q.name: q.read_bytes() for q in folder.iterdir()} == before, fmt

    # ② 两个产物彼此同路：png 与 jpg 都产出 a.webp（目录里本来没有 a.webp，① 的判据盖不住这一维）
    p = run_engine(["-i", folder, "-f", "webp", "-g", "-1", "--no-rename"])
    assert p.returncode == 1, (p.returncode, p.stderr)
    assert "are the same file" in p.stderr, p.stderr
    assert {q.name: q.read_bytes() for q in folder.iterdir()} == before

    # ② 的另一形态：同 stem 不同扩展名（a.png + a.jpeg）配 -f jpg
    jpeg_dir = workdir / "collide-jpeg"
    jpeg_dir.mkdir()
    make_png(jpeg_dir / "a.png", size=(32, 32))
    make_jpg(jpeg_dir / "a.jpeg", size=(32, 32))
    before_jpeg = {p.name: p.read_bytes() for p in jpeg_dir.iterdir()}
    p = run_engine(["-i", jpeg_dir, "-f", "jpg", "-g", "-1", "--no-rename"])
    assert p.returncode == 1, (p.returncode, p.stderr)
    assert "are the same file" in p.stderr, p.stderr
    assert {q.name: q.read_bytes() for q in jpeg_dir.iterdir()} == before_jpeg


@needs_engine
def test_folder_suffix_naming_rejects_colliding_outputs(workdir):
    """工单 70：**开着**后缀段 + 目录里同 stem 不同扩展名 → 两个产物算到同一路径，跑之前拒绝

    实测修复前的静默后果（bld 跑 1.jpg + 1.png 配 -f jpg，遍历顺序 1.jpg 在前）：
    两行都打 done、退出码 0，而产物目录里只有一个 1-(模型名)-n0-2.0x.jpg（后写的盖掉先写的）——
    第一张图白跑了。配 --delete-input 更会两张源图全删、只剩一张产物。
    """
    folder = workdir / "collide-suffix"
    folder.mkdir()
    make_png(folder / "1.png", size=(32, 32))
    make_jpg(folder / "1.jpg", size=(32, 32))
    before = {p.name: p.read_bytes() for p in folder.iterdir()}

    p = run_engine(["-i", folder, "-f", "jpg", "-g", "-1"])
    assert p.returncode == 1, (p.returncode, p.stderr)
    assert "are the same file" in p.stderr, p.stderr
    # 拒绝发生在建输出目录之前：源图一个字节没动、输出目录也不该留下
    assert {q.name: q.read_bytes() for q in folder.iterdir()} == before
    assert not (workdir / f"collide-suffix-{MODEL_TAG}-n0-2.0x").exists()

    # 换 -f same 就不撞了（产物一个是 .jpg、一个是 .png）→ 能跑完，见 test_format_same.py
    p2 = run_engine(["-i", folder, "-f", "same", "-g", "-1"])
    assert p2.returncode == 0, p2.stderr


@needs_engine
def test_no_rename_folder_auto_picks_each_files_own_variant(workdir):
    """目录 + 关后缀段 + AUTO 档位不一致：产物名不带任何段，但每个文件仍按**自己**解析出的档位
    选权重（工单 39 的逐文件档位在关后缀段路径下不得失效）。

    名字上已看不出档位，所以只能比内容：原地产物 vs「同图 + 显式该档位的单文件参考产物」的 PSNR。
    """
    folder = workdir / "mixed"
    folder.mkdir()
    clean = folder / "a.png"
    make_gradient(clean)  # 干净 → 0 档
    dirty = folder / "b.jpg"
    make_gradient(dirty)
    Image.open(dirty).save(dirty, quality=10)  # 重压缩伪影 → 非 0 档
    originals = {p.name: p.read_bytes() for p in folder.iterdir()}  # a.png 会被产物原地覆盖，先存原图

    p = run_engine(["-i", folder, "-m", "waifu2x_cunet", "--denoise", "auto",
                    "-f", "png", "-g", "-1", "-v", "--no-rename"])
    assert p.returncode == 0, p.stderr
    levels = auto_levels_by_file(p.stderr)
    # 顺序守卫：夹具必须保持档位不一致，否则本用例会空转通过
    assert set(levels) == {str(clean), str(dirty)}, levels
    assert len(set(levels.values())) == 2, levels

    assert not (workdir / "mixed-(waifu2x_cunet)-nX-2.0x").exists()
    assert sorted(x.name for x in folder.iterdir()) == ["a.png", "b.jpg", "b.png"]

    # 参考产物：**两张图各跑一次**「同图 + 显式自己那档、默认命名（-n<N> 段可见）」→ 与原地产物比内容。
    # 只比干净那张会漏掉「逐文件档位退化成恒 0」这类回归（脏图产物就没人管了），故逐张比。
    tokens = {0: "none", 1: "low", 2: "mid", 3: "high"}
    for src_name, product_name in (("a.png", "a.png"), ("b.jpg", "b.png")):
        level = levels[str(folder / src_name)]
        refdir = workdir / f"ref-{src_name}"
        refdir.mkdir()
        ref = refdir / src_name
        ref.write_bytes(originals[src_name])
        pr = run_engine(["-i", ref, "-m", "waifu2x_cunet", "--denoise", tokens[level], "-f", "png", "-g", "-1"])
        assert pr.returncode == 0, pr.stderr
        refprod = refdir / f"{ref.stem}-(waifu2x_cunet)-n{level}-2.0x.png"
        assert refprod.exists(), sorted(x.name for x in refdir.iterdir())
        assert psnr(Image.open(folder / product_name), Image.open(refprod)) >= 40.0, (src_name, level)


@needs_engine
def test_no_rename_cyrillic_case_variant_overwrites_in_place(workdir):
    """非 ASCII 文件名 + 两种拼写变体（NTFS 上同一个文件）→ 均原地覆盖，不新增文件。

    两轮各放大 2 倍（32 → 64 → 128）：只有两种拼写都写到同一个文件才会得到 128×128；
    若任一拼写新建了文件，目录内会多出第二个文件，断言随之失败。
    第一轮即与参考产物比 PSNR：内容确为超分结果（实测 99.0 dB），而非同尺寸的别的图。
    """
    folder, on_disk, ref, p1, before = _run_in_place(workdir, "А.PNG")  # 西里尔大写 А + 大写扩展名

    assert p1.returncode == 0, (p1.returncode, p1.stderr)
    _assert_in_place_product(on_disk, ref, size=(64, 64))

    # 两种拼写（大写 / 小写西里尔，小写扩展名）都在 NTFS 上解析到同一个文件
    p2 = run_engine(["-i", folder / "а.png", "-f", "png", "-g", "-1", "--no-rename"])
    assert p2.returncode == 0, (p2.returncode, p2.stderr)
    assert on_disk.read_bytes() != before
    # 第二轮产物是 128×128，参考产物只对应第一轮的 64×64，无可比的 PSNR → 这里只断言格式与尺寸
    second = Image.open(on_disk)
    assert second.format == "PNG"
    assert second.size == (128, 128)
    assert sorted(x.name for x in folder.iterdir()) == ["А.PNG"]


@needs_engine
def test_no_rename_direct_resize_same_format_overwrites_in_place(workdir):
    """直通缩放（目标 < 原图）+ 关后缀段 + 同格式：产物路径即输入路径 → 原地覆盖源文件

    直通缩放（目标 32 < 原图 64）不跑模型，走的是另一条命名分支（`A-(Resize)-32x`）：该分支若
    不落在 no_rename 之后就会多出一个带后缀的产物。尺寸只证明「源文件被替换」，内容才算证明
    「替换成的是直通缩放结果」，故与「同参数但不带 --no-rename」的参考产物比 PSNR（实测 99.0 dB）。
    """
    folder, inp, ref, p, _ = _run_in_place(workdir, "A.png", size=(64, 64), args=["--width", "32"])

    assert p.returncode == 0, (p.returncode, p.stderr)
    # 没有 -(Resize)-32x 段的新产物：目录内只有源文件本身
    assert sorted(x.name for x in folder.iterdir()) == ["A.png"]
    _assert_in_place_product(inp, ref, size=(32, 32))
