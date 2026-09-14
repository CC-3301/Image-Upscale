"""工单 17：引擎输出编码（管道/控制台统一 UTF-8）"""
import pytest

from conftest import make_png, needs_engine, run_engine


@needs_engine
def test_chinese_filename_utf8_output(workdir):
    # 旧引擎经 C locale(GBK) 转宽字符输出，GUI 按 UTF-8 解码 → 乱码
    inp = workdir / "中文测试图.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-s", "2", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    # stderr verbose 行与 stdout 成功行都必须包含原始文件名（UTF-8 可解码）
    assert "中文测试图" in p.stderr, p.stderr
    assert "中文测试图" in p.stdout, p.stdout


@needs_engine
def test_japanese_filename_utf8_output(workdir):
    # GBK 无法表示假名（旧引擎输出 '?'），UTF-8 输出必须完整保留
    inp = workdir / "テスト画像.png"
    make_png(inp, size=(48, 32))
    p = run_engine(["-i", inp, "-s", "2", "-f", "png", "-g", "-1", "-v"])
    assert p.returncode == 0, p.stderr
    assert "テスト画像" in p.stderr, p.stderr
    assert "テスト画像" in p.stdout, p.stdout
