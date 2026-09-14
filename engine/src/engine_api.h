// iu_engine.dll 对外导出面（工单 27：引擎与 GUI 融合，进程内调用）
// 行协议与原 CLI 进程版字节一致：progress d/t / <in> -> <out> done / done，
// 退出码 0 成功 / 1 参数错误 / 2 模型或推理失败 / 3 IO 错误。
#ifndef IU_ENGINE_API_H
#define IU_ENGINE_API_H

#ifdef IU_ENGINE_BUILDING
#define IU_API extern "C" __declspec(dllexport)
#else
#define IU_API extern "C"
#endif

// 行回调：line_utf8 为一行输出（含结尾 '\n'，UTF-8 编码，可能含文件路径）。
// user 为调用方透传上下文；回调在 iu_run 调用线程上同步触发，引擎不并发输出。
typedef void (*iu_line_cb)(const char* line_utf8, void* user);

// 运行一次超分任务（同步，完成后返回）。
// argv[0] 为程序名占位，参数解析从 argv[1] 开始；参数语义与原 CLI 完全一致。
// 非线程安全：同一进程内请串行调用。
// 返回退出码：0 / 1 / 2 / 3（含义见文件头）。
IU_API int iu_run(int argc, const wchar_t* const* argv, iu_line_cb out_cb, iu_line_cb err_cb, void* user);

#endif // IU_ENGINE_API_H
