// 引擎内部统一日志出口（lessons §1.3；工单 46 审查项）
//
// 模型实现（waifu2x / realcugan / realesrgan）与引擎核心共用同一出口：
// 所有输出都经 iu_run 注册的行回调交给宿主（GUI 日志面板），**不再直写 stderr**。
// 原因：GUI 没有控制台，直写 stderr 的内容既看不到，宽字符路径还会乱码。
//
// 用法（模型实现侧）：iu_log_path_error("cannot open model file: ", parampath);
// 注册（引擎核心侧）：iu_set_log_sink(err_cb, user); 在 iu_run 入口调用一次。
#ifndef IU_LOG_H
#define IU_LOG_H

#include <stddef.h>
#include <string>

// 路径类型统一为宽字符（见 iu_path.h），模型侧 load() 的形参也按它取
#include "iu_path.h"
typedef std::wstring iu_path_t;

// 一行 UTF-8 输出（须自带结尾 '\n'）；形参与 engine_api.h 的 iu_line_cb 一致，
// 引擎核心可直接登记宿主回调，无需再包一层适配器
typedef void (*iu_log_sink)(const char* utf8_line, void* user);

// 已登记的出口（回调 + 宿主上下文）
struct iu_sink_slot
{
    iu_log_sink sink = 0;
    void* user = 0;
};

// inline 函数里的局部 static 在所有 TU 中是同一个对象（C++ 标准保证同一实体），
// 所以本头文件可以不带 .cpp —— 新增源文件无需改 CMake 列表
inline iu_sink_slot& iu_sink_ref()
{
    static iu_sink_slot slot;
    return slot;
}

inline void iu_set_log_sink(iu_log_sink sink, void* user)
{
    iu_sink_slot& slot = iu_sink_ref();
    slot.sink = sink;
    slot.user = user;
}

// 宽字符 → UTF-8（平台实现见 iu_path.h）
inline std::string iu_to_utf8(const iu_path_t& s)
{
    return iu_utf8_encode(s);
}

// 输出一行；未注册 sink 时丢弃（绝不退回直写 stderr）
inline void iu_log_line(const std::string& line)
{
    iu_sink_slot& slot = iu_sink_ref();
    if (slot.sink)
        slot.sink(line.c_str(), slot.user);
}

// 便捷：报告与某个文件路径相关的错误（路径统一转 UTF-8）
inline void iu_log_path_error(const char* what, const iu_path_t& path)
{
    iu_log_line(std::string(what) + iu_to_utf8(path) + "\n");
}

#endif // IU_LOG_H
