// image-upscale 引擎 CLI 薄壳（工单 27）
// 核心逻辑已全部移入 iu_engine.dll（engine_core.cpp，导出 iu_run）；
// 本 exe 仅保留控制台入口，作为自动化测试缝（tests/ 的 IU_ENGINE）存在，不再随发布分发。
// 行输出经回调打回控制台，字节流与重构前完全一致（工单 17 的 UTF-8 语义不变）。
#include <stdio.h>
#include <windows.h>

#include "engine_api.h"

#if _WIN32
#define PATH_MAIN wmain
#else
#define PATH_MAIN main
#endif

static void console_out(const char* line, void*)
{
    fputs(line, stdout);
    fflush(stdout);
}

static void console_err(const char* line, void*)
{
    fputs(line, stderr);
    fflush(stderr);
}

int PATH_MAIN(int argc, wchar_t** argv)
{
    // 控制台直跑时切 UTF-8 输出码页（工单 17）；DLL 核心侧不碰控制台状态
    SetConsoleOutputCP(CP_UTF8);
    return iu_run(argc, (const wchar_t* const*)argv, console_out, console_err, NULL);
}
