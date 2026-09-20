"""工单 69：删除输入文件（`--delete-input`）—— 产物**写盘成功之后**删掉源文件

判据全部落在文件系统上（引擎 CLI 是唯一测试缝）：
产物存在 / 源文件是否还在 / 退出码 / stderr 文案。GUI 侧的开关与 setting.ini 无自动化测试（人工验收）。
"""
import ctypes

from PIL import Image

from conftest import MODEL, make_jpg, make_png, needs_engine, run_engine

MODEL_TAG = f"({MODEL})"

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_CREATE_ALWAYS = 2
_OPEN_EXISTING = 3
_INVALID_HANDLE = ctypes.c_void_p(-1).value


def _lock_path(path):
    """以 dwShareMode=0 独占创建并持有 path —— 此后引擎的 `_wfopen(..., L"wb")` 必然失败。

    用来造「写盘失败」场景：持有时长靠调用方 finally 里的 _unlock 控制。
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    handle = k32.CreateFileW(str(path), _GENERIC_WRITE, 0, None, _CREATE_ALWAYS, 0, None)
    assert handle and handle != _INVALID_HANDLE, f"CreateFileW 独占打开失败：{ctypes.get_last_error()}"
    return handle


def _unlock(handle):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CloseHandle(ctypes.c_void_p(handle))


def _open_shared_rw(path):
    """以 dwShareMode = READ|WRITE（**不含 DELETE**）打开并持有 path。

    用来造「删不掉源文件」：读写都允许（引擎能读它、能写它），但 DeleteFile 会被拒。
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    handle = k32.CreateFileW(str(path), _GENERIC_READ | _GENERIC_WRITE, 0x1 | 0x2, None, _OPEN_EXISTING, 0, None)
    assert handle and handle != _INVALID_HANDLE, f"CreateFileW 共享读写打开失败：{ctypes.get_last_error()}"
    return handle


@needs_engine
def test_delete_input_removes_source_after_output_is_written(workdir):
    """单文件 + 异格式：产物 A.jpg 写出后源图 A.png 消失（退出码 0）"""
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.png"
    make_png(inp)

    p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1", "--no-rename", "--delete-input"])
    assert p.returncode == 0, p.stderr
    assert not inp.exists()
    assert Image.open(folder / "A.jpg").size == (128, 128)
    assert sorted(x.name for x in folder.iterdir()) == ["A.jpg"]


@needs_engine
def test_delete_input_is_off_without_the_flag(workdir):
    """默认关：不带旗标时源图必须原封不动（删除不可逆，默认值不许走火）"""
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.png"
    make_png(inp)
    before = inp.read_bytes()

    p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1", "--no-rename"])
    assert p.returncode == 0, p.stderr
    assert inp.read_bytes() == before
    assert sorted(x.name for x in folder.iterdir()) == ["A.jpg", "A.png"]


@needs_engine
def test_delete_input_skipped_when_output_is_the_input_path(workdir):
    """产物与输入同路径（关后缀段 + 同格式 = 原地覆盖，工单 58）：跳过删除

    删掉的就是刚写出的产物 —— 若真删了，A.png 会彻底消失（既是源图也是产物）。
    """
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.png"
    make_png(inp, size=(32, 32))

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1", "-v", "--no-rename", "--delete-input"])
    assert p.returncode == 0, p.stderr
    assert sorted(x.name for x in folder.iterdir()) == ["A.png"]
    assert Image.open(inp).size == (64, 64)  # 产物留下了，且确是超分结果
    assert "input kept (output overwrites it)" in p.stderr


@needs_engine
def test_delete_input_skipped_for_uppercase_extension_overwrite(workdir):
    """扩展名大小写不同也指向同一个文件（NTFS 不区分大小写）→ 同样跳过删除

    路径比较带大小写折叠（lessons §3.13 的 CompareStringOrdinal 口径）：误判成「两个文件」
    就会把 `A.PNG` 删掉，而它就是产物本身。
    """
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.PNG"
    make_png(inp, size=(32, 32))

    p = run_engine(["-i", inp, "-f", "png", "-g", "-1", "--no-rename", "--delete-input"])
    assert p.returncode == 0, p.stderr
    assert sorted(x.name for x in folder.iterdir()) == ["A.PNG"]  # 覆盖不改名
    assert Image.open(inp).size == (64, 64)


@needs_engine
def test_delete_input_folder_input_deletes_every_source(workdir):
    """文件夹输入：逐文件删源图（含子目录），产物照默认命名进输出目录"""
    folder = workdir / "manga"
    (folder / "inner").mkdir(parents=True)
    make_png(folder / "p001.png")
    make_png(folder / "inner" / "p002.png")

    p = run_engine(["-i", folder, "-f", "png", "-g", "-1", "--delete-input"])
    assert p.returncode == 0, p.stderr

    outdir = workdir / f"manga-{MODEL_TAG}-n0-2.0x"
    assert (outdir / "p001.png").exists()
    assert (outdir / "inner" / "p002.png").exists()
    # 源图两张都没了，目录骨架还在（空目录不删，不属本功能范围）
    assert sorted(folder.rglob("*.png")) == []
    assert sorted(x.name for x in folder.iterdir()) == ["inner"]


@needs_engine
def test_delete_input_folder_with_no_rename_converts_in_place(workdir):
    """文件夹 + 关后缀段 + 删除输入 = 整树原地转换：只剩产物，源图消失

    也顺带守住「产物落在输入树里不会被同一轮当成输入再处理一次」（输入清单在跑之前就收齐了）。
    """
    folder = workdir / "conv"
    folder.mkdir()
    make_png(folder / "a.png")
    make_png(folder / "b.png")

    p = run_engine(["-i", folder, "-f", "jpg", "-g", "-1", "--no-rename", "--delete-input"])
    assert p.returncode == 0, p.stderr
    assert sorted(x.name for x in folder.iterdir()) == ["a.jpg", "b.jpg"]
    assert Image.open(folder / "a.jpg").size == (128, 128)


@needs_engine
def test_delete_input_matches_full_name_not_stem(workdir):
    """删除输入文件按**完整文件名**匹配：输入 1.jpg 就删 1.jpg，同目录的 1.png 一个字节不动

    单文件输入时另一张根本不是输入，自然不该被碰；本用例把「按全名而非按去扩展名的 stem 删」钉住。
    """
    folder = workdir / "B"
    folder.mkdir()
    target = folder / "1.jpg"
    bystander = folder / "1.png"
    make_jpg(target, size=(32, 32))
    make_png(bystander, size=(32, 32))
    bystander_before = bystander.read_bytes()

    p = run_engine(["-i", target, "-f", "png", "-g", "-1", "--delete-input"])
    assert p.returncode == 0, p.stderr
    assert not target.exists()
    assert bystander.read_bytes() == bystander_before
    # 产物照常写出（用默认命名，避开「产物正好叫 1.png」而盖住旁观文件的那个语义）
    assert {x.name for x in folder.iterdir()} == {"1.png", f"1-{MODEL_TAG}-n0-2.0x.png"}


@needs_engine
def test_delete_input_failure_keeps_source_and_reports_io_error(workdir):
    """删源文件本身失败（文件被别的进程占用）→ 源图保留、产物已写出、以 IO 错误码 3 收场

    r3 评审 P2 补的覆盖：删除失败分支（log 为 `cannot delete input` + io_failures++）此前只在票面声明。
    造法：以 share mode = READ|WRITE（不含 DELETE）持有源文件 —— 读得到、写不得删；
    引擎先写出产物（-f jpg，目标 A.jpg），随后 _wremove 被拒。
    """
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.png"
    make_png(inp)
    handle = _open_shared_rw(inp)
    try:
        p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1", "--no-rename", "--delete-input"])
    finally:
        _unlock(handle)

    assert p.returncode == 3, (p.returncode, p.stderr)
    assert "cannot delete input" in p.stderr
    assert inp.exists()  # 源图还在（删除失败不回滚已写出的产物，也不假装成功）
    assert Image.open(folder / "A.jpg").size == (128, 128)  # 产物照写


@needs_engine
def test_delete_input_keeps_source_when_write_fails(workdir):
    """写盘失败：源图必须留着（删除只挂在写盘成功之后），且以 IO 错误码 3 收场

    目标文件被独占持有 → 编码写盘必失败。若实现改成「先删再写」，本用例会看到源图消失。
    """
    folder = workdir / "B"
    folder.mkdir()
    inp = folder / "A.png"
    make_png(inp)
    handle = _lock_path(folder / "A.jpg")
    try:
        p = run_engine(["-i", inp, "-f", "jpg", "-g", "-1", "--no-rename", "--delete-input"])
    finally:
        _unlock(handle)

    assert p.returncode == 3, (p.returncode, p.stderr)
    assert inp.exists()
    assert "encode image failed" in p.stderr
