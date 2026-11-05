// 路径与文件打开的平台抽象（引擎内部统一用宽字符保存路径；
// Windows 走 W 版 Win32 API，POSIX 落盘前转 UTF-8）。
// 说明：Linux 的 wchar_t 是 4 字节 UTF-32，与 Windows 的 2 字节 UTF-16 不同，
// 因此编解码必须自己实现，不能直接依赖 wcstombs（受 locale 影响）。
#ifndef IU_PATH_H
#define IU_PATH_H

#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <string>
#include <filesystem>

#if _WIN32
#include <windows.h>
#endif

typedef std::wstring path_t;
#define PATHSTR(X) L##X

// 宽字符路径 → UTF-8（日志与 POSIX 文件 API 使用）
inline std::string iu_utf8_encode(const std::wstring& s)
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
    std::string out;
    out.reserve(s.size());
    for (size_t i = 0; i < s.size(); i++)
    {
        unsigned int cp = (unsigned int)s[i];
        if (cp < 0x80)
        {
            out.push_back((char)cp);
        }
        else if (cp < 0x800)
        {
            out.push_back((char)(0xC0 | (cp >> 6)));
            out.push_back((char)(0x80 | (cp & 0x3F)));
        }
        else if (cp < 0x10000)
        {
            out.push_back((char)(0xE0 | (cp >> 12)));
            out.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back((char)(0x80 | (cp & 0x3F)));
        }
        else
        {
            out.push_back((char)(0xF0 | (cp >> 18)));
            out.push_back((char)(0x80 | ((cp >> 12) & 0x3F)));
            out.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back((char)(0x80 | (cp & 0x3F)));
        }
    }
    return out;
#endif
}

// UTF-8 → 宽字符路径（命令行参数进入引擎时使用）
inline std::wstring iu_utf8_decode(const std::string& s)
{
#if _WIN32
    if (s.empty())
        return std::wstring();
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), NULL, 0);
    std::wstring out((size_t)(n > 0 ? n : 0), L'\0');
    if (n > 0)
        MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), &out[0], n);
    return out;
#else
    std::wstring out;
    out.reserve(s.size());
    size_t i = 0;
    while (i < s.size())
    {
        unsigned char c = (unsigned char)s[i];
        unsigned int cp = 0;
        size_t extra = 0;
        if (c < 0x80) { cp = c; extra = 0; }
        else if ((c & 0xE0) == 0xC0) { cp = c & 0x1F; extra = 1; }
        else if ((c & 0xF0) == 0xE0) { cp = c & 0x0F; extra = 2; }
        else { cp = c & 0x07; extra = 3; }
        for (size_t k = 0; k < extra && i + 1 + k < s.size(); k++)
            cp = (cp << 6) | ((unsigned char)s[i + 1 + k] & 0x3F);
        out.push_back((wchar_t)cp);
        i += 1 + extra;
    }
    return out;
#endif
}

// 宽字符路径 → std::filesystem::path：Windows 直接构造，POSIX 走 u8path（避免 locale 相关转换抛异常）
inline std::filesystem::path iu_fs_path(const std::wstring& s)
{
#if _WIN32
    return std::filesystem::path(s);
#else
    return std::filesystem::u8path(iu_utf8_encode(s));
#endif
}

// std::filesystem::path → 宽字符路径（反向转换）
inline std::wstring iu_fs_path_w(const std::filesystem::path& p)
{
#if _WIN32
    return p.wstring();
#else
    return iu_utf8_decode(p.u8string());
#endif
}

// 宽字符转整数：MSVC 有 _wtoi，POSIX 用 wcstol
inline int iu_wtoi(const wchar_t* s)
{
#if _WIN32
    return _wtoi(s);
#else
    return (int)wcstol(s, NULL, 10);
#endif
}

// 宽字符路径打开文件：Windows 用 _wfopen，POSIX 先转 UTF-8 再 fopen
inline FILE* iu_fopen(const std::wstring& path, const char* mode)
{
#if _WIN32
    std::wstring wmode(mode, mode + strlen(mode));
    return _wfopen(path.c_str(), wmode.c_str());
#else
    std::string p = iu_utf8_encode(path);
    return fopen(p.c_str(), mode);
#endif
}

#endif // IU_PATH_H
