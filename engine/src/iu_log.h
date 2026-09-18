// 引擎内部统一日志出口（lessons §1.3；工单 46 审查项）
//
// 模型实现（waifu2x / realcugan / realesrgan）与引擎核心共用同一出口：
// 所有输出都经 iu_run 注册的行回调交给宿主（GUI 日志面板），**不再直写 stderr**。
// 原因：GUI 没有控制台，直写 stderr 的内容既看不到，宽字符路径还会乱码。
//
// 用法（模型实现侧）：iu_log_path_error("cannot open model file: ", parampath);
// 注册（引擎核心侧）：iu_set_log_sink(&iu_err_sink); 在 iu_run 入口调用一次。
#ifndef IU_LOG_H
#define IU_LOG_H

#include <stddef.h>
#include <string>

#if _WIN32
#include <windows.h>
typedef std::wstring iu_path_t;
#else
typedef std::string iu_path_t;
#endif

// 一行 UTF-8 输出（须自带结尾 '\n'）
typedef void (*iu_log_sink)(const char* utf8_line);

// inline 函数里的局部 static 在所有 TU 中是同一个对象（C++ 标准保证同一实体），
// 所以本头文件可以不带 .cpp —— 新增源文件无需改 CMake 列表
inline iu_log_sink& iu_sink_ref()
{
    static iu_log_sink sink = 0;
    return sink;
}

inline void iu_set_log_sink(iu_log_sink sink)
{
    iu_sink_ref() = sink;
}

// 宽字符 → UTF-8（Windows 走 WideCharToMultiByte；其他平台路径本就是窄字符，直接透传）
inline std::string iu_to_utf8(const iu_path_t& s)
{
#if _WIN32
    if (s.empty())
        return std::string();
    int n = WideCharToMultiByte(CP_UTF8, 0, s.c_str(), (int)s.size(), NULL, NULL, NULL, NULL);
    std::string out((size_t)(n > 0 ? n : 0), '\0');
    if (n > 0)
        WideCharToMultiByte(CP_UTF8, 0, s.c_str(), (int)s.size(), &out[0], n, NULL, NULL);
    return out;
#else
    return s;
#endif
}

// 输出一行；未注册 sink 时丢弃（绝不退回直写 stderr）
inline void iu_log_line(const std::string& line)
{
    if (iu_sink_ref())
        iu_sink_ref()(line.c_str());
}

// 便捷：报告与某个文件路径相关的错误（路径统一转 UTF-8）
inline void iu_log_path_error(const char* what, const iu_path_t& path)
{
    iu_log_line(std::string(what) + iu_to_utf8(path) + "\n");
}

#endif // IU_LOG_H
