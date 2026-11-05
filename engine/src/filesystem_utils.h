#ifndef FILESYSTEM_UTILS_H
#define FILESYSTEM_UTILS_H

#include <stdio.h>
#include <vector>
#include <string>
#include <algorithm>

#include "iu_path.h"

#if _WIN32
#include <windows.h>
#include "win32dirent.h"
#else // _WIN32
#include <unistd.h>
#include <filesystem>
#endif // _WIN32

#if _WIN32
static bool path_is_directory(const path_t& path)
{
    DWORD attr = GetFileAttributesW(path.c_str());
    return (attr != INVALID_FILE_ATTRIBUTES) && (attr & FILE_ATTRIBUTE_DIRECTORY);
}

static int list_directory(const path_t& dirpath, std::vector<path_t>& imagepaths)
{
    imagepaths.clear();

    _WDIR* dir = _wopendir(dirpath.c_str());
    if (!dir)
    {
        // 不在此直接打印：宽字符路径经 stderr 输出会乱码，且绕过引擎回调（lessons §1.3）
        return -1;
    }

    struct _wdirent* ent = 0;
    while ((ent = _wreaddir(dir)))
    {
        if (ent->d_type != DT_REG && ent->d_type != DT_LNK)
            continue;

        imagepaths.push_back(path_t(ent->d_name));
    }

    _wclosedir(dir);
    std::sort(imagepaths.begin(), imagepaths.end());

    return 0;
}
#else // _WIN32
static bool path_is_directory(const path_t& path)
{
    // POSIX 文件 API 只接受窄字符，统一转 UTF-8 后再交给 std::filesystem
    std::error_code ec;
    return std::filesystem::is_directory(std::filesystem::u8path(iu_utf8_encode(path)), ec);
}

static int list_directory(const path_t& dirpath, std::vector<path_t>& imagepaths)
{
    imagepaths.clear();

    std::error_code ec;
    std::filesystem::directory_iterator it(std::filesystem::u8path(iu_utf8_encode(dirpath)), ec);
    if (ec)
    {
        // 同上：不绕过引擎回调直接打印
        return -1;
    }

    for (const std::filesystem::directory_entry& ent : it)
    {
        std::error_code type_ec;
        if (!ent.is_regular_file(type_ec) && !ent.is_symlink(type_ec))
            continue;

        imagepaths.push_back(iu_utf8_decode(ent.path().filename().u8string()));
    }

    std::sort(imagepaths.begin(), imagepaths.end());

    return 0;
}
#endif // _WIN32

static path_t get_file_name_without_extension(const path_t& path)
{
    size_t dot = path.rfind(PATHSTR('.'));
    if (dot == path_t::npos)
        return path;

    return path.substr(0, dot);
}

static path_t get_file_extension(const path_t& path)
{
    size_t dot = path.rfind(PATHSTR('.'));
    if (dot == path_t::npos)
        return path_t();

    return path.substr(dot + 1);
}

#if _WIN32
static path_t get_executable_directory()
{
    wchar_t filepath[256];
    GetModuleFileNameW(NULL, filepath, 256);

    wchar_t* backslash = wcsrchr(filepath, L'\\');
    backslash[1] = L'\0';

    return path_t(filepath);
}
#elif __APPLE__
static path_t get_executable_directory()
{
    char filepath[256];
    uint32_t size = sizeof(filepath);
    _NSGetExecutablePath(filepath, &size);

    char* slash = strrchr(filepath, '/');
    slash[1] = '\0';

    return path_t(filepath);
}
#else
static path_t get_executable_directory()
{
    char filepath[4096];
    ssize_t n = readlink("/proc/self/exe", filepath, sizeof(filepath) - 1);
    if (n <= 0)
        return path_t();
    filepath[n] = '\0';

    char* slash = strrchr(filepath, '/');
    if (slash)
        slash[1] = '\0';

    return iu_utf8_decode(filepath);
}
#endif

static bool filepath_is_readable(const path_t& path)
{
    FILE* fp = iu_fopen(path, "rb");
    if (!fp)
        return false;

    fclose(fp);
    return true;
}

static path_t sanitize_filepath(const path_t& path)
{
    if (filepath_is_readable(path))
        return path;

    return get_executable_directory() + path;
}

#endif // FILESYSTEM_UTILS_H
