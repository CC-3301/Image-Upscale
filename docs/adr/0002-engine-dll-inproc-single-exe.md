---
status: accepted
---

# 0002 - 引擎与 GUI 融合：iu_engine.dll 进程内调用，发布单一 ImageUpscale.exe

## Context

ADR-0001 把引擎交付为独立 exe（GUI 以子进程调用），CLI 能力免费获得。维护者于 v0.2.2 迭代（工单 27）决定：**放弃 CLI 支持**，把引擎与 GUI 融合为单个 `ImageUpscale.exe`，去掉分发布的 `engine/` 目录。

曾评估的融合方式：

- **引擎 exe 嵌入 GUI 资源、运行时解压**（方案 A）：引擎零改动，但分发形态是"自解压"，磁盘上仍落一个 exe。
- **引擎编译为 DLL，GUI P/Invoke 直调**（方案 B，**已采纳**）：真单文件；代价是引擎 main 需拆分重构、行协议改经回调、新增 DLL 导出缝测试。
- 引擎编译为静态库链入托管进程：需要托管 C++/反向 P/Invoke 结构，复杂度更高，否决。

## Decision

- 引擎核心自 `main.cpp` 抽离为 `engine_core.cpp`，编译为 `iu_engine.dll`，导出 C API：
  `int iu_run(int argc, const wchar_t* const* argv, iu_line_cb out_cb, iu_line_cb err_cb, void* user)`
  参数为宽字符数组（免引号转义），输出为 UTF-8 行回调；**行协议（`progress d/t` / `<in> -> <out> done` / `done`）与退出码（0/1/2/3）语义不变**。
- GUI（`ImageUpscale.exe`）经 P/Invoke 进程内调用；models 目录由 GUI 定位并显式传 `--models-dir`（models 定位单一定义来源，lessons §1.4）。
- 发布形态：自包含单文件 `ImageUpscale.exe`（`iu_engine.dll` 以 Content 进单文件包，`IncludeNativeLibrariesForSelfExtract` 使其在首次启动解压至 `%TEMP%\.net` 后加载）+ `models/` + 许可文档；打包脚本守卫包根不得出现散装 dll/pdb。
- 另构建 CLI 薄壳 `image-upscale.exe`（仅控制台回调 + `SetConsoleOutputCP`），**不随发布分发**，专作自动化测试缝（tests/ 的 `IU_ENGINE`）。

## Consequences

- 进程边界消失：引擎级崩溃（如 0xC0000005）会波及宿主进程；退出码翻译逻辑保留，崩溃表现为汇总行的异常退出码提示。
- 第三方不再能把引擎当独立 CLI 使用（被放弃的能力）；自动化测试改走两条缝：薄壳 exe（行为回归）+ ctypes 直调 DLL（导出契约）。
- 单文件包首次启动在 `%TEMP%\.net\<hash>\` 留有引擎解压缓存（后续启动复用），属 .NET 单文件官方行为。
