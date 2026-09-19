"""启动日志文案守卫（工单 33 原始口径 / 工单 52 回归修复）

GUI 是 WPF，没有 UI 测试接缝，启动行只能把源码字面量钉住：这条文案被改过两次
（33 原定不带「引擎」→ 2026-09-19 被补成「引擎就绪」→ 52 回退），光靠人工验收守不住。
"""
import re

from conftest import REPO

MAIN_WINDOW = REPO / "gui" / "MainWindow.xaml.cs"


def _startup_lines():
    """取出 MainWindow 里所有 Log($"...") 文案，供逐字断言"""
    src = MAIN_WINDOW.read_text(encoding="utf-8")
    return src, re.findall(r'Log\(\$?"([^"]*)"\)', src)


def test_startup_line_wording_is_exact():
    _, lines = _startup_lines()
    assert "就绪，已加载 {_models.Count} 个模型" in lines, lines


def test_engine_prefix_not_reintroduced():
    src, _ = _startup_lines()
    assert "引擎就绪" not in src


def test_error_lines_unchanged():
    _, lines = _startup_lines()
    assert any("未找到 models 目录" in s for s in lines), lines
    assert any("manifest.conf 解析失败或为空" in s for s in lines), lines
