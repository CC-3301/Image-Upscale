// 引擎核心（工单 27 自 main.cpp 抽离，随 iu_engine.dll 分发）
// 全部逻辑与输出点不变；输出经 log_out/log_err 回调（字节流与原 CLI 一致）。
// 命令面、命名规则、格式/质量控制为本项目原创；
// tiled 推理内核适配自 nihui/waifu2x-ncnn-vulkan、realcugan-ncnn-vulkan、
// Real-ESRGAN-ncnn-vulkan（均 MIT，见 NOTICE.md）
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <map>
#include <string>
#include <vector>
#include <algorithm>
#include <clocale>
#include <exception>
#include <filesystem>

#if _WIN32
#include <windows.h>
#include <shlwapi.h> // StrCmpLogicalW：序列化重命名的排序口径（与资源管理器一致）
#endif

// stb 为头文件库，实现必须在唯一包含点展开
#define STB_IMAGE_IMPLEMENTATION
#define STB_IMAGE_WRITE_IMPLEMENTATION
#define STB_IMAGE_RESIZE_IMPLEMENTATION
#include "stb_image.h"
#include "stb_image_write.h"
#include "stb_image_resize2.h"
#include "webp_image.h"

// ncnn
#include "cpu.h"
#include "gpu.h"
#include "platform.h"

#include "waifu2x.h"
#include "realcugan.h"
#include "realesrgan.h"

#include "filesystem_utils.h"
#include "iu_log.h" // 引擎内部统一日志出口（模型实现与引擎核心共用，禁止直写 stderr）

#include "engine_api.h"
#include <cstdarg>

// ---- 输出 shim（工单 27）：全部输出点经调用方回调；行内容含结尾换行，UTF-8 ----
static iu_line_cb g_out_cb;
static iu_line_cb g_err_cb;
static void* g_user;

static void vlog(iu_line_cb cb, const char* fmt, va_list ap)
{
    if (!cb)
        return;
    va_list ap2;
    va_copy(ap2, ap);
    const int n = vsnprintf(NULL, 0, fmt, ap2);
    va_end(ap2);
    if (n <= 0)
        return;
    std::string s((size_t)n, '\0');
    vsnprintf(&s[0], (size_t)n + 1, fmt, ap);
    cb(s.c_str(), g_user);
}

static void log_out(const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vlog(g_out_cb, fmt, ap);
    va_end(ap);
}

static void log_err(const char* fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vlog(g_err_cb, fmt, ap);
    va_end(ap);
}

static void print_usage()
{
    log_out("Usage: image-upscale -i input-path [options]...\n\n");
    log_out("  -i input-path        input image (jpg/jpeg/png/webp) or directory\n");
    log_out("  -m model-id          model id from models/manifest.conf (default: waifu2x_upconv_7_art)\n");
    log_out("  -s scale             ratio mode: native scale of the model (default: 2.0)\n");
    log_out("  --width N            target-size mode: target width (exclusive with -s/--height)\n");
    log_out("  --height N           target-size mode: target height (exclusive with -s/--width)\n");
    log_out("  --denoise level      none/low/mid/high (default: none; model must support it)\n");
    log_out("  --down-filter f      resize filter when shrinking: lanczos/catmullrom/bicubic/box\n");
    log_out("                       (default: lanczos; only for shrinking — upscaling uses model passes)\n");
    log_out("  -f format            output image format jpg/png/webp/same (default: jpg; same = follow each input)\n");
    log_out("  -q quality           output quality 0-100 for jpg/webp (default: 90)\n");
    log_out("  -t tile-size         tile size (>=32/0=auto, default: 0)\n");
    log_out("  -g gpu-id            gpu device (-1=cpu, default: auto)\n");
    log_out("  --models-dir path    models directory (default: models)\n");
    log_out("  --suffix mode        where the -(model)-nN-<scale> segment goes: both (default) /\n");
    log_out("                       folder / file / none (folder = only the output folder name,\n");
    log_out("                       file = only the product file name, none = no segment)\n");
    log_out("  --no-rename          same as --suffix none: name the output after the input file\n");
    log_out("  --delete-input       delete the input file after its output is written to a temp file,\n");
    log_out("                       before the rename (skipped when the output overwrites the input)\n");
    log_out("  --sequence           name the products 001, 002, ... in each folder's natural order\n");
    log_out("                       (3-digit padding, more digits past 999; source names never change)\n");
    log_out("  -v                   verbose output\n");
    log_out("  -h                   show this help\n");
}

// 退出码：0 成功 / 1 参数错误 / 2 模型或推理失败 / 3 IO 错误
enum ExitCode
{
    EXIT_OK = 0,
    EXIT_PARAM = 1,
    EXIT_INFER = 2,
    EXIT_IO = 3
};

// ---- 模型清单（与 GUI 共享格式） ----
struct ModelInfo
{
    std::string id;
    std::string display;
    std::string group;
    std::string arch;  // waifu2x | cugan | rrdb | compact
    std::string dir;
    std::vector<int> scales;
    std::map<int, int> prepad; // scale → prepadding
    std::string in_blob;
    std::string out_blob;
    std::string tileauto; // upconv | cunet | cugan | realesrgan
    std::map<int, std::string> denoise; // 0=无 1=低 2=中 3=高 → 变体 token
    bool pro = false; // cugan 权重需 [0.15,0.85] 仿射归一化（工单 40）
};

static bool parse_manifest(const path_t& path, std::vector<ModelInfo>& out)
{
    FILE* fp = iu_fopen(path, "rb");
    if (!fp)
        return false;

    ModelInfo cur;
    bool any = false;
    char line[1024];
    auto flush = [&]() {
        if (any && !cur.id.empty())
        {
            out.push_back(cur);
            cur = ModelInfo();
            any = false;
        }
    };

    while (fgets(line, sizeof(line), fp))
    {
        std::string l = line;
        if (!l.empty() && (l[0] == '\xEF'))
            l = l.substr(3);
        while (!l.empty() && (l.back() == '\n' || l.back() == '\r' || l.back() == ' '))
            l.pop_back();
        if (l.empty() || l[0] == '#')
            continue;

        size_t sp = l.find(' ');
        if (sp == std::string::npos)
            continue;
        std::string key = l.substr(0, sp);
        std::string val = l.substr(sp + 1);

        if (key == "model")
        {
            flush();
            cur.id = val;
            any = true;
        }
        else if (key == "display") cur.display = val;
        else if (key == "group") cur.group = val;
        else if (key == "arch") cur.arch = val;
        else if (key == "dir") cur.dir = val;
        else if (key == "scale") cur.scales.push_back(atoi(val.c_str()));
        else if (key == "prepad")
        {
            size_t sp2 = val.find(' ');
            if (sp2 == std::string::npos)
            {
                for (int s : cur.scales)
                    cur.prepad[s] = atoi(val.c_str());
            }
            else
            {
                cur.prepad[atoi(val.substr(0, sp2).c_str())] = atoi(val.substr(sp2 + 1).c_str());
            }
        }
        else if (key == "in") cur.in_blob = val;
        else if (key == "out") cur.out_blob = val;
        else if (key == "tileauto") cur.tileauto = val;
        else if (key == "pro") cur.pro = (val == "yes");
        else if (key == "denoise")
        {
            size_t sp2 = val.find(' ');
            if (sp2 != std::string::npos)
            {
                std::string lvl = val.substr(0, sp2);
                int level = lvl == "none" ? 0 : lvl == "low" ? 1 : lvl == "mid" ? 2 : lvl == "high" ? 3 : -1;
                if (level >= 0)
                    cur.denoise[level] = val.substr(sp2 + 1);
            }
        }
    }
    fclose(fp);
    flush();
    return true;
}

// ---- 引擎多态包装：尺寸模式需要按文件倍数重载模型 ----
struct IEngine
{
    virtual int load_files(const std::wstring& parampath, const std::wstring& binpath) = 0;
    virtual int process(const ncnn::Mat& inimage, ncnn::Mat& outimage) const = 0;
    virtual void configure(int scale, int denoise_level, int tilesize, int prepadding) = 0;
    virtual ~IEngine() = default;
};

struct Waifu2xEngine : IEngine
{
    Waifu2x impl;
    Waifu2xEngine(int gpuid, int num_threads) : impl(gpuid, false, num_threads) {}
    int load_files(const std::wstring& p, const std::wstring& b) override { return impl.load(p, b); }
    int process(const ncnn::Mat& in, ncnn::Mat& out) const override { return impl.process(in, out); }
    void configure(int scale, int denoise_level, int tilesize, int prepadding) override
    {
        impl.noise = denoise_level;
        impl.scale = scale;
        impl.tilesize = tilesize;
        impl.prepadding = prepadding;
    }
};

struct CuganEngine : IEngine
{
    RealCUGAN impl;
    CuganEngine(int gpuid, int num_threads, bool pro) : impl(gpuid, false, num_threads) { impl.pro = pro; }
    int load_files(const std::wstring& p, const std::wstring& b) override { return impl.load(p, b); }
    int process(const ncnn::Mat& in, ncnn::Mat& out) const override { return impl.process(in, out); }
    void configure(int scale, int denoise_level, int tilesize, int prepadding) override
    {
        impl.noise = denoise_level;
        impl.scale = scale;
        impl.tilesize = tilesize;
        impl.prepadding = prepadding;
        // 同步档位固定 2（rough sync，工单 38）：上游默认档位 3（very rough）用固定的 32px
        // 小图块平均 SE 描述子，会把 realcugan-pro / no-denoise 权重推出分布（整幅彩色噪声），
        // 也会给 realcugan-se / no-denoise 留下线条边缘的黄边彩噪；档位 3 还只覆盖 3 的倍数
        // 个图块，尾部图块无人写入。档位 2 用与 tilesize 同尺寸的图块正确同步描述子，耗时 +5%。
        // 2026-09-18 复测确认 1/2 是“纹理 vs 色度噪点”的取舍：1=accurate 纹理贴近原图
        // （网点窗高频 48.3，原图 47.1）但色度噪点 5.02%；2=rough 色度噪点 0.44% 但纹理偏平（35.9）。
        // 官方 ncnn 二进制同样如此（-c 1 彩噪 4.35% / -c 2 0.80%，pro 偏暖 +2.97 / +0.63），
        // 属上游 SE 同步近似所致，暂不追。
        // 不可达代码警示（2026-09-19 审查）：档位 3（very rough）的缓存网格与 stage2 不一致
        // （very_rough 按 32px 网格写键、stage2 按 tilesize 读键，且尾部图块无人写入），
        // realcugan.cpp 里 syncgap==3 的分支启用后会静默出坏图。此处固定 2 即令其不可达，勿改回 3。
        impl.syncgap = 2;
    }
};

struct RealesrganEngine : IEngine
{
    RealESRGAN impl;
    RealesrganEngine(int gpuid, int num_threads) : impl(gpuid, num_threads, false) {}
    int load_files(const std::wstring& p, const std::wstring& b) override { return impl.load(p, b); }
    int process(const ncnn::Mat& in, ncnn::Mat& out) const override { return impl.process(in, out); }
    void configure(int scale, int denoise_level, int tilesize, int prepadding) override
    {
        impl.scale = scale;
        impl.tilesize = tilesize;
        impl.prepadding = prepadding;
    }
};

// stb 写文件回调：聚合到内存缓冲
struct MemBuffer
{
    std::vector<unsigned char> data;
};

static void stb_write_callback(void* context, void* data, int size)
{
    MemBuffer* buf = (MemBuffer*)context;
    const unsigned char* p = (const unsigned char*)data;
    buf->data.insert(buf->data.end(), p, p + size);
}

static bool write_file_wide(const std::wstring& path, const unsigned char* data, size_t len)
{
    FILE* fp = iu_fopen(path, "wb");
    if (!fp)
        return false;
    size_t written = fwrite(data, 1, len, fp);
    fclose(fp);
    return written == len;
}

// alpha 拍平到白底：RGBA -> RGB（alpha 全流程在工单 04 实现）
static unsigned char* flatten_alpha_to_white(unsigned char* pixeldata, int w, int h)
{
    unsigned char* rgb = (unsigned char*)malloc((size_t)w * h * 3);
    if (!rgb)
        return NULL;
    for (int i = 0; i < w * h; i++)
    {
        const unsigned char* px = pixeldata + (size_t)i * 4;
        unsigned char* out = rgb + (size_t)i * 3;
        for (int ch = 0; ch < 3; ch++)
        {
            int a = px[3];
            out[ch] = (unsigned char)((px[ch] * a + 255 * (255 - a) + 127) / 255);
        }
    }
    return rgb;
}

// 灰度（可能带 alpha）→ RGB
static unsigned char* gray_to_rgb(unsigned char* pixeldata, int w, int h, int c)
{
    unsigned char* rgb = (unsigned char*)malloc((size_t)w * h * 3);
    if (!rgb)
        return NULL;
    for (int p = 0; p < w * h; p++)
    {
        const unsigned char* px = pixeldata + (size_t)p * c;
        unsigned char* out = rgb + (size_t)p * 3;
        int a = c == 2 ? px[1] : 255;
        for (int ch = 0; ch < 3; ch++)
            out[ch] = (unsigned char)((px[0] * a + 255 * (255 - a) + 127) / 255);
    }
    return rgb;
}


// 伪影启发式估计（工单 06）：JPEG 块效应差分 → 规范降噪档位（0=无 1=低 2=中 3=高）
// 仅看亮度近似（R 通道）以保持确定性；降采样限速
static int estimate_denoise_level(const unsigned char* rgb, int w, int h)
{
    if (w < 9 || h < 2)
        return 0;

    const int step = std::max(1, w / 256);

    // 水平块效应：8 像素块边界差分 vs 块内差分
    double b_sum = 0, i_sum = 0;
    long b_n = 0, i_n = 0;
    for (int y = 0; y < h; y += step)
    {
        const unsigned char* row = rgb + (size_t)y * w * 3;
        for (int x = 1; x < w; x += step)
        {
            int d = abs(row[(size_t)x * 3] - row[(size_t)(x - 1) * 3]);
            if (x % 8 == 0) { b_sum += d; b_n++; }
            else { i_sum += d; i_n++; }
        }
    }
    double boundary = b_n ? b_sum / b_n : 0.0;
    double inner = i_n ? i_sum / i_n : 0.0;
    double blockiness = boundary - inner;
    if (blockiness < 0)
        blockiness = 0;

    // 垂直方向同判（JPEG 8x8 块两轴皆有）
    double bv_sum = 0, iv_sum = 0;
    long bv_n = 0, iv_n = 0;
    for (int y = 1; y < h; y += step)
    {
        const unsigned char* row = rgb + (size_t)y * w * 3;
        const unsigned char* prev = row - (size_t)w * 3;
        for (int x = 0; x < w; x += step)
        {
            int d = abs(row[(size_t)x * 3] - prev[(size_t)x * 3]);
            if (y % 8 == 0) { bv_sum += d; bv_n++; }
            else { iv_sum += d; iv_n++; }
        }
    }
    double vboundary = bv_n ? bv_sum / bv_n : 0.0;
    double vinner = iv_n ? iv_sum / iv_n : 0.0;
    double vblockiness = vboundary - vinner;
    if (vblockiness < 0)
        vblockiness = 0;

    const double score = (blockiness + vblockiness) / 2.0;
    if (score >= 6.0)
        return 3;
    if (score >= 2.5)
        return 2;
    if (score >= 0.8)
        return 1;
    return 0;
}

// 首文件降噪探测（工单 39）：AUTO 的档位逐文件解析，而输出目录名必须在建目录前定下来，
// 只能体现首文件档位——故先解一次首文件。解码/内存失败返回 0（等同"无降噪"）。
static int probe_denoise_level(const path_t& path, const path_t& format)
{
    FILE* fp = iu_fopen(path, "rb");
    if (!fp)
        return 0;
    fseek(fp, 0, SEEK_END);
    long length = ftell(fp);
    rewind(fp);
    if (length <= 0)
    {
        fclose(fp);
        return 0;
    }
    unsigned char* filedata = (unsigned char*)malloc((size_t)length);
    if (!filedata)
    {
        fclose(fp);
        return 0;
    }
    size_t rd = fread(filedata, 1, length, fp);
    fclose(fp);
    if (rd != (size_t)length)
    {
        free(filedata);
        return 0;
    }

    unsigned char* pixeldata = 0;
    int w = 0, h = 0, c = 0;
    if (length > 12 && memcmp(filedata, "RIFF", 4) == 0 && memcmp(filedata + 8, "WEBP", 4) == 0)
        pixeldata = webp_load(filedata, (int)length, &w, &h, &c);
    if (!pixeldata)
        pixeldata = stbi_load_from_memory(filedata, (int)length, &w, &h, &c, 0);
    free(filedata);
    if (!pixeldata)
        return 0;

    // 与 run_files 的解码后处理保持一致：估计器只看 RGB 三通道
    unsigned char* rgb = pixeldata;
    if (c == 4 && format != PATHSTR("jpg"))
    {
        rgb = (unsigned char*)malloc((size_t)w * h * 3);
        if (rgb)
            for (int i = 0; i < w * h; i++)
                memcpy(rgb + (size_t)i * 3, pixeldata + (size_t)i * 4, 3);
    }
    else if (c == 4)
    {
        rgb = flatten_alpha_to_white(pixeldata, w, h);
    }
    else if (c == 1 || c == 2)
    {
        rgb = gray_to_rgb(pixeldata, w, h, c);
    }

    int level = 0;
    if (rgb)
    {
        level = estimate_denoise_level(rgb, w, h);
        if (rgb != pixeldata)
            free(rgb);
    }
    free(pixeldata);
    return level;
}

// 模型目录规范化（确保尾部分隔符，便于拼接 manifest.conf）
static std::wstring mi_dir(const std::wstring& dir)
{
    if (!dir.empty() && dir.back() != L'/')
        return dir + L"/";
    return dir;
}

// ASCII → 宽字符（清单 id/变体 token 均为 ASCII，足够）
static std::wstring widen(const std::string& s)
{
    return std::wstring(s.begin(), s.end());
}

// ---- 降采样滤镜（工单 42）：只在“缩小”路径生效；放大一律由多轮模型完成（工单 43）----
// 名字沿用界面标签（三次卷积家族里 Bicubic/Mitchell/Catmull-Rom 常被混用，本项目里
// Bicubic = Mitchell-Netravali、Catmull-Rom = 插值型三次卷积）
enum ResizeFilter
{
    RF_LANCZOS3 = 0, // 界面 Lanczos：Lanczos-3，最锐，可能振铃
    RF_CATMULLROM,   // 界面 Catmull-Rom：较锐，轻微振铃
    RF_BICUBIC,      // 界面 Bicubic：Mitchell-Netravali，无振铃、较柔
    RF_BOX,          // 界面 Box：面积平均（stb 的梯形/盒核，整数倍时等同盒式）
};

static const wchar_t* const kDownFilterNames[] = { L"lanczos", L"catmullrom", L"bicubic", L"box" };
static const int kDownFilterCount = (int)(sizeof(kDownFilterNames) / sizeof(kDownFilterNames[0]));

// Lanczos-3 核：sinc(x) * sinc(x/3)。stb 传进来的 x 已是输出像素单位，
// 缩小时由其内部按 1/scale 放宽支持域（与内置核同约定），故支持域恒为 3。
static float lanczos3_kernel(float x, float scale, void* user_data)
{
    (void)scale; (void)user_data;
    if (x < 0.0f) x = -x;
    if (x < 1e-6f) return 1.0f;
    if (x >= 3.0f) return 0.0f;
    const float px = 3.14159265358979323846f * x;
    return (3.0f * sinf(px) * sinf(px / 3.0f)) / (px * px);
}

static float lanczos3_support(float scale, void* user_data)
{
    (void)scale; (void)user_data;
    return 3.0f;
}

// 高质量等比缩放（通道数 1/3/4；输出为 uchar 交错布局）
// down_filter：仅用于“缩小”（目标尺寸模式的收尾缩放、直通缩放）；
// 放大已由多轮模型完成（工单 43），这里的非缩小分支只是保底（如收尾尺寸因四舍五入
// 比模型输出多 1 像素），用 RF_BICUBIC（= Mitchell-Netravali，工单 42 的定名）。
static bool resize_rgb(const ncnn::Mat& src, ncnn::Mat& dst, int out_w, int out_h, int channels, int down_filter)
{
    stbir_pixel_layout layout = (stbir_pixel_layout)channels;
    dst.create(out_w, out_h, (size_t)channels, channels); // 与引擎 outimage 约定一致（编码器以 elempack 为通道数）

    const bool shrinking = out_w < src.w && out_h < src.h;
    const int filter = shrinking ? down_filter : RF_BICUBIC;

    if (filter == RF_LANCZOS3)
    {
        // stb 没有内置 Lanczos，走自定义核（高级 API）
        STBIR_RESIZE r;
        stbir_resize_init(&r, src.data, src.w, src.h, src.w * channels,
            dst.data, out_w, out_h, out_w * channels, layout, STBIR_TYPE_UINT8);
        if (!stbir_set_filter_callbacks(&r, lanczos3_kernel, lanczos3_support, lanczos3_kernel, lanczos3_support))
        {
            return false;
        }
        return stbir_resize_extended(&r) != 0;
    }

    stbir_filter builtin = STBIR_FILTER_CATMULLROM;
    switch (filter)
    {
    case RF_BICUBIC: builtin = STBIR_FILTER_MITCHELL; break;
    case RF_BOX:     builtin = STBIR_FILTER_BOX; break;
    default:         builtin = STBIR_FILTER_CATMULLROM; break; // RF_CATMULLROM
    }
    return stbir_resize((const unsigned char*)src.data, src.w, src.h, src.w * channels,
        (unsigned char*)dst.data, out_w, out_h, out_w * channels,
        layout, STBIR_TYPE_UINT8, STBIR_EDGE_CLAMP, builtin) != 0;
}

// 目标尺寸模式的原生档计划（工单 43）：放大一律由模型完成，不做插值放大
// 规则：在“轮数最少”的方案里取“累积倍率最小”的档位组合（每轮一个可用原生档）——
//   1) 存在单档 ≥ 目标倍率 → 就是那一档（与旧行为一致、收尾缩放最温和）；
//   2) 目标超过模型最大原生档 → 逐轮叠加（如 2x 模型要 3 倍 → 2x 再 2x = 4x，再缩小）。
// 计划保证累积尺寸 ≥ 目标，收尾 resize 永远是缩小。
static void plan_dfs(const std::vector<int>& scales, double ratio, int depth, int maxdepth,
                     double acc, std::vector<int>& cur, std::vector<int>& best, double& best_acc)
{
    if (acc >= ratio)
    {
        if (best.empty() || acc < best_acc || (acc == best_acc && cur.size() < best.size()))
        {
            best = cur;
            best_acc = acc;
        }
        return;
    }
    if (depth == maxdepth)
        return;
    for (int s : scales)
    {
        cur.push_back(s);
        plan_dfs(scales, ratio, depth + 1, maxdepth, acc * s, cur, best, best_acc);
        cur.pop_back();
    }
}

static std::vector<int> plan_native_scales(const ModelInfo& mi, double ratio)
{
    std::vector<int> best;
    if (mi.scales.empty())
        return best;

    std::vector<int> cur;
    double best_acc = 0.0;
    plan_dfs(mi.scales, ratio, 0, 12, 1.0, cur, best, best_acc);
    if (!best.empty())
        return best;

    // 兜底（比率大到 12 轮仍不达标，正常不会走到）：用最小原生档重复
    const int smin = mi.scales.front();
    double acc = 1.0;
    while (acc < ratio)
    {
        best.push_back(smin);
        acc *= smin;
    }
    return best;
}

// ---- 模型文件解析（按架构与倍数/降噪档） ----
static bool resolve_model_files(const std::wstring& models_dir, const ModelInfo& mi, int scale, int denoise_level,
                                path_t& parampath, path_t& binpath, int& prepadding)
{
    path_t model_dir = models_dir + PATHSTR("/") + widen(mi.dir);

    // 档位必须由清单声明：AUTO 按文件估计出的档位（如 1/2）在只有 无/高 的模型上并不存在，
    // 早期直接 .at() 会抛 std::out_of_range 且无人捕获 → std::terminate（拖垮宿主 GUI）。
    auto dit = mi.denoise.find(denoise_level);
    if (dit == mi.denoise.end())
        return false;
    const std::string& token = dit->second;

    if (mi.arch == "waifu2x")
    {
        char seg[32];
        snprintf(seg, sizeof(seg), "noise%s_scale2.0x_model", token.c_str());
        parampath = sanitize_filepath(model_dir + PATHSTR("/") + widen(seg) + PATHSTR(".param"));
        binpath = sanitize_filepath(model_dir + PATHSTR("/") + widen(seg) + PATHSTR(".bin"));
    }
    else if (mi.arch == "cugan")
    {
        char seg[64];
        snprintf(seg, sizeof(seg), "up%dx-%s", scale, token.c_str());
        parampath = sanitize_filepath(model_dir + PATHSTR("/") + widen(seg) + PATHSTR(".param"));
        binpath = sanitize_filepath(model_dir + PATHSTR("/") + widen(seg) + PATHSTR(".bin"));
    }
    else
    {
        parampath = sanitize_filepath(models_dir + PATHSTR("/") + widen(mi.dir + "/" + token + ".param"));
        binpath = sanitize_filepath(models_dir + PATHSTR("/") + widen(mi.dir + "/" + token + ".bin"));
    }
    prepadding = mi.prepad.count(scale) ? mi.prepad.at(scale) : 0;
    return true;
}

// 产物名的命名段（工单 02 命名规则 / 工单 39 逐文件档位 / 工单 50 无后缀）
// 工单 61：run_files 与 single_file_outpath 共用同一份，不再逐个位置传参
// 工单 65：构造一律具名赋值，不依赖字段顺序
// 工单 71：`ext` 字段已删 —— 输出扩展名改为**逐文件**参数（`--format same` 时跟随每个输入自己的扩展名），
// 不再是整批一个值，故不进命名段
struct NamingSegments
{
    std::wstring display;     // 模型显示名（产物名的 -(<display>) 段）
    std::wstring denoise_seg; // 降噪段（-nN；直通缩放不写）
    std::wstring scale_seg;   // 倍率/尺寸段（2.0x / 128x）
};

// 添加后缀四态：决定 -(模型名)-nN-<倍率|尺寸> 段落在输出文件夹名上还是产物文件名上
// （直通缩放的 -(Resize)-<尺寸> 段同一条规则）
enum SuffixMode
{
    SUFFIX_BOTH = 0,   // 开（两者，默认）：段在输出文件夹名上，产物文件名按 AUTO 逐文件档位补 -nN
    SUFFIX_FOLDER = 1, // 开（文件夹）：段只在输出文件夹名上，产物文件名永远干净
    SUFFIX_FILE = 2,   // 开（文件）：不建输出目录，段整段落在产物文件名上
    SUFFIX_NONE = 3    // 关：都不带
};

// 是否建输出目录、把段挂在该目录名上（开（两者）/开（文件夹））
static bool suffix_uses_folder(SuffixMode mode)
{
    return mode == SUFFIX_BOTH || mode == SUFFIX_FOLDER;
}

// 段是否落在产物文件名上（开（两者）/开（文件））。单文件输入没有输出文件夹可挂段，按这一条判：
// 落文件名时写整段，开（文件夹）/关时产物 = 原文件名 + 输出格式扩展名
static bool suffix_puts_segment_in_name(SuffixMode mode)
{
    return mode == SUFFIX_BOTH || mode == SUFFIX_FILE;
}

// 产物文件名是否补 -nN（段在文件名上时才补）：开（文件）恒补；开（两者）只在 AUTO 逐文件档位
// 不一致时补；开（文件夹）/关的文件名永远干净；直通缩放不跑模型，不带降噪段。
// **只作用于目录输入的产物文件名**：单文件输入走 single_file_outpath，那边恒写整段。
// run_files 与跑前撞车守卫共用这一处 —— 判据手抄两份时「只改一处」就是静默错名
static std::wstring product_denoise_seg(SuffixMode suffix, bool direct_resize, bool denoise_per_file,
                                        const std::wstring& file_denoise_seg)
{
    if (direct_resize || !suffix_puts_segment_in_name(suffix))
        return std::wstring();
    if (suffix == SUFFIX_BOTH && !denoise_per_file)
        return std::wstring();
    return file_denoise_seg;
}

// 运行期标量参数（工单 61）：构造一律具名赋值（工单 65），不依赖字段顺序
// 类内初值取「未设置」语义：quality=-1 / run_scale=0 / target_value=0 均在各自合法域之外，
// 漏填不会被当成有效值；tilesize=0 等于 CLI 的「自动」，down_filter 等于 CLI 默认的 Lanczos
struct RunOptions
{
    path_t format;                       // 输出编码容器（jpg/png/webp）；空串不是哨兵：无人校验，会落进 WebP 分支
    int quality = -1;                    // jpg/webp 质量（合法域 0-100）
    int run_scale = 0;                   // 倍率模式的原生倍数（合法域 ≥1）
    bool target_mode = false;            // 目标尺寸模式
    int target_value = 0;                // 目标宽或高（合法域 >0）
    bool target_is_width = true;         // target_value 是宽（与 CLI 默认一致）
    int down_filter = RF_LANCZOS3;       // 降采样滤镜（与 CLI 默认同源：RF_LANCZOS3）
    int tilesize = 0;                    // 0 = 按显存自动
    bool denoise_auto = false;
    bool verbose = false;
    SuffixMode suffix = SUFFIX_BOTH; // 四态：段落在输出文件夹名上还是产物文件名上
    bool delete_input = false; // 写成完整 tmp 后、改名成目标前删除（源与目标同路径时跳过）
    bool format_same = false;  // 工单 71：输出格式跟随每个输入自己的格式（扩展名保留输入拼写）
    bool sequence = false;     // 序列化重命名：产物名主干换成按自然序发的 001/002/…
};

// 工单 69/68：路径比较的公共口径（lessons §3.13）—— 先 weakly_canonical，把「输入写 A.PNG、
// 产物写 A.png」这类写法差异归一到盘上真实大小写；再用 CompareStringOrdinal(..., TRUE) 做大小写
// 不敏感比较（不用 towlower：其结果依赖进程 locale）。规范化失败（不存在 / 非法路径）时退回原串
static std::wstring canonical_path_key(const path_t& p)
{
    std::error_code ec;
    const std::filesystem::path c = std::filesystem::weakly_canonical(iu_fs_path(p), ec);
    return ec ? p : iu_fs_path_w(c);
}

// 大小写不敏感的严格弱序（口径同上）—— 供「按路径建索引」的容器使用（工单 68 的产物撞输入检测），
// 不必先把路径折成小写串：折大小写要么依赖 locale、要么自写规则，都是多一个真相来源
#if !_WIN32
// 只折叠 ASCII：不依赖 locale，跨机器结果一致（Windows 侧用 CompareStringOrdinal 的不变语义）
static wchar_t ordinal_lower(wchar_t c)
{
    return (c >= L'A' && c <= L'Z') ? (wchar_t)(c - L'A' + L'a') : c;
}
#endif

struct OrdinalLess
{
    bool operator()(const std::wstring& a, const std::wstring& b) const
    {
#if _WIN32
        return CompareStringOrdinal(a.c_str(), (int)a.size(), b.c_str(), (int)b.size(), TRUE) == CSTR_LESS_THAN;
#else
        const size_t n = a.size() < b.size() ? a.size() : b.size();
        for (size_t i = 0; i < n; i++)
        {
            const wchar_t ca = ordinal_lower(a[i]);
            const wchar_t cb = ordinal_lower(b[i]);
            if (ca != cb)
                return ca < cb;
        }
        return a.size() < b.size();
#endif
    }
};

// 序列化重命名的排序口径：数字按大小、字母不分大小写；中文的拼音序来自 Windows 系统 collation
// （StrCmpLogicalW 是资源管理器自身用的比较器，中文按系统 locale 排），只在 Windows 上成立。
// 非 Windows 分支只有开发与测试用途，按「数字按值 → ASCII 字母忽略大小写 → 其余按序数」近似，
// 不做拼音：排序结果不承诺与 Windows 一致
static int compare_natural(const std::wstring& a, const std::wstring& b)
{
#if _WIN32
    return StrCmpLogicalW(a.c_str(), b.c_str());
#else
    size_t i = 0;
    size_t j = 0;
    while (i < a.size() && j < b.size())
    {
        const bool a_digit = a[i] >= L'0' && a[i] <= L'9';
        const bool b_digit = b[j] >= L'0' && b[j] <= L'9';
        if (a_digit && b_digit)
        {
            // 数字段按值比较：跳过前导零后先比位数（位数少的更小），位数相同再逐位比
            size_t ai = i;
            size_t bj = j;
            while (ai < a.size() && a[ai] == L'0')
                ai++;
            while (bj < b.size() && b[bj] == L'0')
                bj++;
            size_t ae = ai;
            size_t be = bj;
            while (ae < a.size() && a[ae] >= L'0' && a[ae] <= L'9')
                ae++;
            while (be < b.size() && b[be] >= L'0' && b[be] <= L'9')
                be++;
            const size_t alen = ae - ai;
            const size_t blen = be - bj;
            if (alen != blen)
                return alen < blen ? -1 : 1;
            for (size_t k = 0; k < alen; k++)
            {
                if (a[ai + k] != b[bj + k])
                    return a[ai + k] < b[bj + k] ? -1 : 1;
            }
            // 数值相等（如 1 与 01）→ 继续比后续字符
            i = ae;
            j = be;
            continue;
        }
        const wchar_t ca = ordinal_lower(a[i]);
        const wchar_t cb = ordinal_lower(b[j]);
        if (ca != cb)
            return ca < cb ? -1 : 1;
        i++;
        j++;
    }
    if (i < a.size())
        return 1;
    if (j < b.size())
        return -1;
    return 0;
#endif
}

// 工单 69：两张路径是否指向**同一个文件** —— 判据是「产物原地覆盖了输入」时不得删输入
// （删的就是刚写出的产物）
static bool path_equal_ci(const path_t& a, const path_t& b)
{
    const std::wstring ka = canonical_path_key(a);
    const std::wstring kb = canonical_path_key(b);
    const OrdinalLess less;
    return !less(ka, kb) && !less(kb, ka); // 等价 = 互不小于
}

// 目标路径已存在、且它与 p 的文件名只有拼写（大小写）不同时，返回盘上的真实目录项名；否则返回空串。
// 用途：rename 以源名为准落地，若目标已存在（原地覆盖源文件、覆盖上一轮产物），直接把 tmp 改名
// 成计算出的 outpath 会把目录项改写成 outpath 的拼写 —— NTFS 大小写不敏感，A.PNG 配 `-f png`
// 时 outpath 是 A.png，同一个文件的名字却会被改写成 A.png。weakly_canonical 会把已存在的部分解析回
// 真实大小写（与路径比较用同一口径，见 canonical_path_key）。
// 只认「同一名字、仅拼写不同」：名字实质不同时（如目标是指向别处的符号链接）不动，避免顺着链接
// 把产物写到另一个文件上。
static path_t case_variant_entry_name(const path_t& p)
{
    std::error_code ec;
    if (!std::filesystem::exists(iu_fs_path(p), ec) || ec)
        return path_t();
    const std::filesystem::path resolved = std::filesystem::weakly_canonical(iu_fs_path(p), ec);
    if (ec)
        return path_t();
    const path_t actual = iu_fs_path_w(resolved.filename());
    const path_t want = iu_fs_path_w(iu_fs_path(p).filename());
    const OrdinalLess less;
    const bool same_ci = !less(actual, want) && !less(want, actual);
    return (same_ci && actual != want) ? actual : path_t();
}

// 序列化重命名的产物名主干：目录内按自然序从 001 起编号，3 位补零，序号超过 999 时自然变 4 位
static std::wstring sequence_stem(int index)
{
    wchar_t buf[16];
    swprintf(buf, 16, L"%03d", index);
    return buf;
}

// 产物撞车守卫的门控（跑前守卫与运行期守卫共用同一判据）：「序列化重命名」与「删除输入文件」
// 都关时才拒绝撞车；任一打开即用户主动进入命名/清理模式，产物一律覆盖、不报错
static bool collision_guard_enabled(bool sequence, bool delete_input)
{
    return !sequence && !delete_input;
}

// 单文件输出的命名（工单 02 命名规则）
// SR 路径：A-(模型名)-[nN-]<倍率|尺寸>；直通缩放：A-(Resize)-<尺寸>
// 四态：单文件输入没有输出文件夹可挂段 —— 开（两者）/开（文件）把段写在产物文件名上，
// 开（文件夹）与关等价，产物 = A.<输出格式扩展名>（同格式即原地覆盖源文件）
// file_denoise_seg 是**本文件**解析出的降噪段（AUTO 时逐文件不同），不取自 naming.denoise_seg（批量档位段）
// file_ext 是**本文件**的产物扩展名（`--format same` 时跟随输入，故不进 naming）
// stem 是产物名主干：序列化重命名时是编号（单文件恒为 001），否则是源文件名
static path_t single_file_outpath(const std::filesystem::path& in, const std::wstring& stem,
                                  const NamingSegments& naming, const std::wstring& file_denoise_seg,
                                  const path_t& file_ext, bool direct_resize, SuffixMode suffix)
{
    if (!suffix_puts_segment_in_name(suffix))
        return iu_fs_path_w(in.parent_path() / iu_fs_path(stem + L"." + file_ext));
    if (direct_resize)
        return iu_fs_path_w(in.parent_path() / iu_fs_path(stem + L"-(Resize)-" + naming.scale_seg + L"." + file_ext));
    return iu_fs_path_w(in.parent_path() / iu_fs_path(stem + L"-(" + naming.display + L")" + file_denoise_seg + L"-" +
                                                  naming.scale_seg + L"." + file_ext));
}

// 工单 71：输入扩展名 → 编码器 token（jpeg/jpg → jpg；大小写不敏感）。
// 返回空串 = 不是本工具支持的图片扩展名（调用方已先经 ext_is_image 校验）
static path_t encoder_of_input_extension(const path_t& ext)
{
    path_t e = ext;
    std::transform(e.begin(), e.end(), e.begin(), ::towlower);
    if (e == PATHSTR("jpg") || e == PATHSTR("jpeg"))
        return PATHSTR("jpg");
    if (e == PATHSTR("png"))
        return PATHSTR("png");
    if (e == PATHSTR("webp"))
        return PATHSTR("webp");
    return path_t();
}

// 工单 71：本文件的输出格式 —— 产物扩展名与编码器（`-f same` 时逐文件跟随输入：扩展名保留输入拼写，
// 编码器把 jpeg 归一到 jpg）。run_files / AUTO 探测 / 跑前守卫三处共用这一处 ——
// 公式分叉的后果是静默写出与后缀不符的字节或产物名算错
struct OutputFormat
{
    path_t ext; // 产物扩展名（不含点）
    path_t enc; // 编码器（jpg/png/webp）
};

static OutputFormat output_format_of(const path_t& inpath, bool format_same, const path_t& format)
{
    OutputFormat f;
    if (!format_same)
    {
        f.ext = format;
        f.enc = format;
        return f;
    }
    f.ext = get_file_extension(iu_fs_path_w(iu_fs_path(inpath).filename()));
    f.enc = encoder_of_input_extension(f.ext);
    return f;
}

// 目录模式的产物路径：out_base 已去掉扩展名 —— 开（两者）/开（文件夹）时是输出目录内的相对路径
// （段在目录名上），开（文件）/关时是源文件同目录的原路径；file_denoise_seg 为空即文件名干净
// （开（文件夹）、关，以及开（两者）且全批同档）。跑前守卫与 run_files 共用这一处 ——
// 公式手抄两份时“只改一处”就是静默错名
static path_t dir_product_path(const path_t& out_base, const NamingSegments& naming,
                               const std::wstring& file_denoise_seg, const path_t& file_ext,
                               bool direct_resize, SuffixMode suffix)
{
    if (suffix_uses_folder(suffix))
        return out_base + file_denoise_seg + L"." + file_ext;
    if (suffix == SUFFIX_FILE)
    {
        if (direct_resize)
            return out_base + L"-(Resize)-" + naming.scale_seg + L"." + file_ext;
        return out_base + L"-(" + naming.display + L")" + file_denoise_seg + L"-" + naming.scale_seg + L"." + file_ext;
    }
    return out_base + L"." + file_ext;
}

// 解码 → 推理/直通缩放 → 编码 循环（顺序流水，进度行输出到 stdout）
// 引擎类只需提供 process(in, out) const；模板避免多套重复代码
template <typename Engine>
static int run_files(Engine* engine, const std::wstring& models_dir, const ModelInfo& mi,
                     const std::vector<path_t>& input_files, const std::vector<path_t>& output_files,
                     bool single_file, bool denoise_per_file, int denoise_level,
                     const NamingSegments& naming, const RunOptions& opt)
{
    const int total = (int)input_files.size();
    int done = 0;
    int infer_failures = 0;
    int io_failures = 0;
    // 开（文件夹）+ 单文件没有输出文件夹可挂段，产物就是源文件本身（同格式即原地覆盖）→ 结尾提示一句
    path_t overwrote_input; // 空 = 没有发生原地覆盖；非空 = 被覆盖的那个输入路径

    auto advance_progress = [&]() {
        done++;
        log_out("progress %d/%d\n", done, total);
    };
    auto fail = [&](bool inference_failure, const char* msg, const path_t& path) {
        log_err("%s: %s\n", msg, iu_to_utf8(path).c_str());
        if (inference_failure)
            infer_failures++;
        else
            io_failures++;
        advance_progress();
    };

    // 当前已加载的模型倍数与降噪档（尺寸模式可能按文件切换倍数；AUTO 会按文件切换降噪档）
    // 两者任一变化都必须重载权重：只比较倍数会让“上一文件非零档、本文件 0 档”沿用旧变体出图，
    // 而命名与配置却按本文件档位写（工单 39 的静默错配）
    int loaded_scale = -1;
    int loaded_denoise = -1;
    path_t cur_param, cur_bin;
    int cur_prepad = 0;

    // 本轮已写出的产物路径（规范化 + 大小写不敏感）→ 输入序号，防两个输入写同一路径
    std::map<std::wstring, size_t, OrdinalLess> written;
    // 本批输入的规范化路径 → 序号（运行期「产物撞上同批另一个输入」的判据，键与跑前守卫同一个）
    std::map<std::wstring, size_t, OrdinalLess> input_index;
    for (size_t k = 0; k < input_files.size(); k++)
        input_index[canonical_path_key(input_files[k])] = k;

    for (int i = 0; i < total; i++)
    {
        const path_t& inpath = input_files[i];

        // 解码
        unsigned char* pixeldata = 0;
        int w = 0;
        int h = 0;
        int c = 0;
        {
            FILE* fp = iu_fopen(inpath, "rb");
            if (!fp)
            {
                fail(false, "cannot open input", inpath);
                continue;
            }

            fseek(fp, 0, SEEK_END);
            long length = ftell(fp);
            rewind(fp);
            // ftell / malloc 都必须校验：文件不可定位或内存不足时，
            // 原先会直接 fread(NULL) 造成访问违例（宿主进程级崩溃）
            unsigned char* filedata = length > 0 ? (unsigned char*)malloc((size_t)length) : 0;
            if (!filedata)
            {
                fclose(fp);
                fail(false, "cannot read input", inpath);
                continue;
            }
            size_t rd = fread(filedata, 1, length, fp);
            fclose(fp);

            if (rd != (size_t)length)
            {
                fail(false, "cannot read input", inpath);
                free(filedata);
                continue;
            }

            // webp（RIFF....WEBP 魔数）优先，其余交给 stb（jpg/png 自动识别）
            if (length > 12 && memcmp(filedata, "RIFF", 4) == 0 && memcmp(filedata + 8, "WEBP", 4) == 0)
            {
                pixeldata = webp_load(filedata, (int)length, &w, &h, &c);
            }
            if (!pixeldata)
            {
                pixeldata = stbi_load_from_memory(filedata, (int)length, &w, &h, &c, 0);
            }
            free(filedata);
        }

        if (!pixeldata)
        {
            fail(false, "decode image failed", inpath);
            continue;
        }

        // 工单 71：本文件的产物扩展名与编码器 —— `-f same` 时逐文件跟随输入
        // （扩展名保留输入拼写：`.jpeg` 产物就叫 `.jpeg`；编码器把 jpeg 归一到 jpg —— 同一套编码）
        const OutputFormat file_fmt = output_format_of(inpath, opt.format_same, opt.format);

        // alpha 处理（工单 04）：PNG/WebP 输出保留并同步放大；JPG 输出与白底合成
        bool has_alpha = false;
        std::vector<unsigned char> alpha_src;
        std::vector<unsigned char> alpha_merged; // 工单 15：生存期必须覆盖合并→编码→写盘（旧代码块作用域导致 use-after-free）
        std::vector<unsigned char> alpha_chain_in;   // 工单 43：alpha 过模型时的 3 通道复制缓冲
        std::vector<unsigned char> alpha_chain_out;  // 工单 43：alpha 模型输出取第 0 通道后的单通道缓冲
        if (c == 4 && file_fmt.enc != PATHSTR("jpg"))
        {
            has_alpha = true;
            alpha_src.resize((size_t)w * h);
            for (int i = 0; i < w * h; i++)
                alpha_src[i] = pixeldata[(size_t)i * 4 + 3];
            unsigned char* rgb = (unsigned char*)malloc((size_t)w * h * 3);
            if (!rgb)
            {
                free(pixeldata); // OOM 路径同样要释放已解码缓冲
                fail(false, "out of memory", inpath);
                continue;
            }
            for (int i = 0; i < w * h; i++)
                memcpy(rgb + (size_t)i * 3, pixeldata + (size_t)i * 4, 3);
            free(pixeldata);
            pixeldata = rgb;
            c = 3;
        }
        else if (c == 4)
        {
            unsigned char* rgb = flatten_alpha_to_white(pixeldata, w, h);
            if (!rgb)
            {
                free(pixeldata); // 助手失败时不接管入参，调用方负责释放
                fail(false, "out of memory", inpath);
                continue;
            }
            pixeldata = rgb;
            c = 3;
        }
        else if (c == 1 || c == 2)
        {
            unsigned char* rgb = gray_to_rgb(pixeldata, w, h, c);
            if (!rgb)
            {
                free(pixeldata); // 同上
                fail(false, "out of memory", inpath);
                continue;
            }
            pixeldata = rgb;
            c = 3;
        }

        if (opt.verbose)
        {
            log_err("loaded %s (%dx%d)\n", iu_to_utf8(inpath).c_str(), w, h);
        }

        // 目标尺寸模式的每文件决策：指定维度 ≥ 原图 → 超分；< 原图 → 直通缩放
        // AUTO：按当前文件伪影估计规范档位（单文件命名与模型变体都使用解析结果）
        int file_denoise = denoise_level;
        if (opt.denoise_auto)
        {
            file_denoise = estimate_denoise_level(pixeldata, w, h);
            if (opt.verbose)
                log_err("denoise: auto resolved level=%d\n", file_denoise);
        }

        bool use_engine = true;
        // 本文件要跑的原生档序列（工单 43）：倍率模式固定单轮；目标尺寸模式按计划多轮，
        // 放大全部交给模型，收尾只做缩小
        std::vector<int> plan;
        if (opt.target_mode)
        {
            const int orig_dim = opt.target_is_width ? w : h;
            if (opt.target_value < orig_dim)
            {
                use_engine = false;
            }
            else
            {
                plan = plan_native_scales(mi, (double)opt.target_value / (double)orig_dim);
            }
        }
        if (plan.empty())
        {
            // 倍率模式固定单轮 run_scale；目标尺寸模式倍率 ≤ 1（如 --width 等于原宽）
            // 时计划为空，用最小原生档跑一轮再缩回目标（与旧行为一致）
            plan.push_back(opt.target_mode ? mi.scales.front() : opt.run_scale);
        }

        // 输出路径（单文件按 SR/直通分别命名；文件夹预构建）
        std::wstring file_denoise_seg = opt.denoise_auto
            ? (L"-n" + std::to_wstring(file_denoise))
            : naming.denoise_seg;
        path_t outpath;
        if (single_file)
        {
            std::filesystem::path in = iu_fs_path(inpath);
            // 序列化重命名：单文件输入的产物编号恒为 001（本目录只处理它一张）
            const std::wstring stem = opt.sequence ? sequence_stem(1) : iu_fs_path_w(in.stem());
            outpath = single_file_outpath(in, stem, naming, file_denoise_seg, file_fmt.ext, !use_engine,
                                          opt.suffix);
        }
        else
        {
            const std::wstring name_denoise_seg =
                product_denoise_seg(opt.suffix, !use_engine, denoise_per_file, file_denoise_seg);
            outpath = dir_product_path(output_files[i], naming, name_denoise_seg, file_fmt.ext, !use_engine, opt.suffix);
        }

        // 运行期守卫：产物名在跑前算不准的那几路由这里兜底，两条判据与跑前守卫同口径，
        // 命中都拒绝写盘、按 IO 失败计（静默覆盖的代价是产物被丢、或源图未处理就被盖掉，日志却两行都成功）。
        //   ① 产物撞上**同批另一个输入文件** —— 跑前守卫在「逐文件档位」与「开（文件）+ 目标尺寸」
        //      两路整块跳过，这里补上；
        //   ② 产物与**已写出的产物**同路 —— 如 AUTO 逐文件档位下两个同名输入解析出同一档位。
        // 每个序号只过一次本循环：①比序号即排除「产物覆盖自己」，②命中即必是别的输入写的。
        // 门控与跑前守卫同一判据（collision_guard_enabled）：「序列化重命名」与「删除输入文件」
        // 都关时才拒绝；任一打开即用户主动进入命名/清理模式，一律覆盖、不报错。
        if (collision_guard_enabled(opt.sequence, opt.delete_input))
        {
            const std::wstring key = canonical_path_key(outpath);
            auto in_it = input_index.find(key);
            if (in_it != input_index.end() && in_it->second != (size_t)i)
            {
                fail(false, "output path is another input file", outpath);
                continue;
            }
            if (written.find(key) != written.end())
            {
                fail(false, "output path already written by another input", outpath);
                continue;
            }
            written[key] = (size_t)i;
        }

        // 产物路径与输入路径相同（同目录 + 同扩展名，NTFS 下大小写不敏感）时直接原地覆盖源文件：
        // 同名即直接覆盖，没有例外 —— 无二次确认、无提示，也不备份源图。
        // 原地覆盖的安全性：输入在解码阶段一次性读入内存后立即 fclose（本函数上方解码块），写盘发生在
        // 推理/直通缩放与 alpha 合成之后，中途不再读输入路径 —— 不存在「写到一半又被读」的通路。

        // 放大链（工单 43）：按 plan 逐轮跑模型；每轮确保权重与档位跟当轮原生档匹配。
        // 轮与轮之间不插值，放大完全由模型完成（对齐 waifu2x 的循环放大 + 收尾缩小）。
        // 定义在 use_engine 分支之外：alpha 通道也要走同一条链。
        auto run_chain = [&](ncnn::Mat& cur) -> bool
        {
            for (size_t pi = 0; pi < plan.size(); ++pi)
            {
                const int s = plan[pi];
                if (s != loaded_scale || file_denoise != loaded_denoise)
                {
                    if (!resolve_model_files(models_dir, mi, s, file_denoise, cur_param, cur_bin, cur_prepad))
                    {
                        log_err("model %s has no denoise level %d\n", mi.id.c_str(), file_denoise);
                        fail(true, "model load failed", inpath);
                        return false;
                    }
                    if (engine->load_files(cur_param, cur_bin) != 0)
                    {
                        log_err("model files: %s\n", iu_to_utf8(cur_param).c_str());
                        fail(true, "model load failed", inpath);
                        return false;
                    }
                    loaded_scale = s;
                    loaded_denoise = file_denoise;
                    if (opt.verbose)
                    {
                        // 工单 06：verbose 要能看出解析出的档位最终落到哪个模型变体文件
                        log_err("engine loaded scale=%dx denoise=%d prepad=%d\n", s, file_denoise, cur_prepad);
                        log_err("model variant: %s\n", iu_to_utf8(cur_param).c_str());
                    }
                }
                engine->configure(s, file_denoise, opt.tilesize, cur_prepad);
                if (opt.verbose && plan.size() > 1)
                {
                    log_err("pass %d/%d scale=%dx\n", (int)pi + 1, (int)plan.size(), s);
                }

                ncnn::Mat next(cur.w * s, cur.h * s, (size_t)3, 3);
                if (engine->process(cur, next) != 0 || next.empty())
                {
                    // 各引擎实现内部仍以 return 0 为主（extract 失败不上报），
                    // 这里补一道出口校验：推理没产出就按失败计，避免静默写出坏图
                    fail(true, "inference failed", inpath);
                    return false;
                }
                cur = next; // ncnn::Mat 带引用计数，赋值即接管（工单 15 的生存期教训）
            }
            return true;
        };

        ncnn::Mat outimage;
        if (use_engine)
        {
            ncnn::Mat cur(w, h, (void*)pixeldata, (size_t)3, 3); // 首轮输入为解码缓冲（非拥有）
            const bool chain_ok = run_chain(cur);
            free(pixeldata);
            if (!chain_ok)
            {
                continue;
            }

            if (!opt.target_mode)
            {
                outimage = cur;
            }
            else
            {
                // 精确 resize 到目标（宽/高按指定维度，另一维度等比）
                int exact_w, exact_h;
                if (opt.target_is_width)
                {
                    exact_w = opt.target_value;
                    exact_h = std::max(1, (int)((double)h * opt.target_value / w + 0.5));
                }
                else
                {
                    exact_h = opt.target_value;
                    exact_w = std::max(1, (int)((double)w * opt.target_value / h + 0.5));
                }
                if (cur.w == exact_w && cur.h == exact_h)
                {
                    outimage = cur;
                }
                else if (!resize_rgb(cur, outimage, exact_w, exact_h, 3, opt.down_filter))
                {
                    fail(false, "resize failed", inpath);
                    continue;
                }
            }
        }
        else
        {
            // 直通缩放：跳过推理，等比缩放直达目标（宽/高按指定维度）
            int exact_w, exact_h;
            if (opt.target_is_width)
            {
                exact_w = opt.target_value;
                exact_h = std::max(1, (int)((double)h * opt.target_value / w + 0.5));
            }
            else
            {
                exact_h = opt.target_value;
                exact_w = std::max(1, (int)((double)w * opt.target_value / h + 0.5));
            }
            ncnn::Mat inimage(w, h, (void*)pixeldata, (size_t)3, 3);
            if (!resize_rgb(inimage, outimage, exact_w, exact_h, 3, opt.down_filter))
            {
                fail(false, "resize failed", inpath);
                free(pixeldata);
                continue;
            }
            free(pixeldata);
        }

        // alpha 合成（RGB 超分结果 + 同步放大的 alpha → RGBA）
        // 工单 43：alpha 也走同一条模型放大链（waifu2x 亦然：把 alpha 当单通道图过同一个网络），
        // 收尾同样只做缩小 —— 插值放大会在透明边缘留下光晕/振铃
        if (has_alpha)
        {
            ncnn::Mat alpha_out;
            if (use_engine)
            {
                alpha_chain_in.resize((size_t)w * h * 3);
                for (size_t i = 0; i < (size_t)w * h; ++i)
                {
                    const unsigned char a = alpha_src[i];
                    alpha_chain_in[i * 3] = a;
                    alpha_chain_in[i * 3 + 1] = a;
                    alpha_chain_in[i * 3 + 2] = a;
                }
                ncnn::Mat alpha_cur(w, h, alpha_chain_in.data(), (size_t)3, 3);
                if (!run_chain(alpha_cur))
                {
                    continue;
                }

                // 取第 0 通道 → 单通道，再缩到输出尺寸（永远不是放大）
                alpha_chain_out.resize((size_t)alpha_cur.w * alpha_cur.h);
                const unsigned char* ap = (const unsigned char*)alpha_cur.data;
                for (size_t i = 0; i < alpha_chain_out.size(); ++i)
                {
                    alpha_chain_out[i] = ap[i * 3];
                }
                ncnn::Mat alpha_native(alpha_cur.w, alpha_cur.h, alpha_chain_out.data(), (size_t)1, 1);
                if (alpha_native.w == outimage.w && alpha_native.h == outimage.h)
                {
                    alpha_out = alpha_native;
                }
                else if (!resize_rgb(alpha_native, alpha_out, outimage.w, outimage.h, 1, opt.down_filter))
                {
                    fail(false, "resize failed", inpath);
                    continue;
                }
            }
            else
            {
                // 直通缩放：不跑模型，alpha 与 RGB 同样只做缩小
                ncnn::Mat alpha_in(w, h, (void*)alpha_src.data(), (size_t)1, 1);
                if (!resize_rgb(alpha_in, alpha_out, outimage.w, outimage.h, 1, opt.down_filter))
                {
                    fail(false, "resize failed", inpath);
                    continue;
                }
            }
            alpha_merged.resize((size_t)outimage.w * outimage.h * 4);
            const unsigned char* rgbp = (const unsigned char*)outimage.data;
            for (int i = 0; i < outimage.w * outimage.h; i++)
            {
                alpha_merged[(size_t)i * 4] = rgbp[(size_t)i * 3];
                alpha_merged[(size_t)i * 4 + 1] = rgbp[(size_t)i * 3 + 1];
                alpha_merged[(size_t)i * 4 + 2] = rgbp[(size_t)i * 3 + 2];
                alpha_merged[(size_t)i * 4 + 3] = ((const unsigned char*)alpha_out.data)[i];
            }
            outimage = ncnn::Mat(outimage.w, outimage.h, (void*)alpha_merged.data(), (size_t)4, 4);
        }

        // 编码（按输出格式；质量参数作用于 jpg/webp）—— file_fmt.enc 是本文件的编码器（工单 71）
        // 写盘顺序固定为「同目录临时文件 → 删源（删除输入文件打开时）→ 改名成目标」：直接截断
        // 写目标时中断会留下半截图；先写临时文件则目标要么是旧内容、要么是完整的新产物。
        // 先删源再改名，改名失败时完整产物仍留在临时文件里。临时名固定为「目标名 + .iu-tmp」——
        // 不是图片扩展名，二次运行不会被当成输入。
        const path_t tmppath = outpath + L".iu-tmp";
        bool encode_ok = false;
        bool write_ok = false;
        if (file_fmt.enc == PATHSTR("jpg"))
        {
            MemBuffer buf;
            encode_ok = stbi_write_jpg_to_func(stb_write_callback, &buf, outimage.w, outimage.h, outimage.elempack, outimage.data, opt.quality) != 0;
            if (encode_ok)
                write_ok = write_file_wide(tmppath, buf.data.data(), buf.data.size());
        }
        else if (file_fmt.enc == PATHSTR("png"))
        {
            MemBuffer buf;
            encode_ok = stbi_write_png_to_func(stb_write_callback, &buf, outimage.w, outimage.h, outimage.elempack, outimage.data, outimage.w * outimage.elempack) != 0;
            if (encode_ok)
                write_ok = write_file_wide(tmppath, buf.data.data(), buf.data.size());
        }
        else // webp：编码与写盘合成一次调用，用返回值区分是哪一步失败
        {
            const int webp_rc = webp_save(tmppath.c_str(), outimage.w, outimage.h, outimage.elempack, (const unsigned char*)outimage.data, (float)opt.quality);
            encode_ok = webp_rc >= 0;
            write_ok = webp_rc == 1;
        }

        // 写盘失败要清掉可能已落下的半截临时文件：磁盘满 / 无权限时会写出残文件；
        // 编码是纯内存操作、没写过 tmp，此时不动它（那里可能是上次崩掉留下的完整产物）；
        // 成功时 rename 已把 tmp 带走。改名失败不清 —— 那时临时文件是完整产物（见下）
        auto discard_temp = [&]() {
            std::error_code rec;
            std::filesystem::remove(iu_fs_path(tmppath), rec);
        };
        if (!encode_ok)
        {
            fail(false, "encode image failed", outpath);
            continue;
        }
        if (!write_ok)
        {
            // 编码已成功，失败的是写盘（磁盘满 / 无权限 / 路径不可写），报编码失败会误导
            discard_temp();
            fail(false, "cannot write output", outpath);
            continue;
        }
        // 删除输入文件 —— 在改名之前执行：改名失败时源已删，完整产物仍留在临时文件里（路径写进日志）。
        // 产物与输入同路径（原地覆盖）时跳过删除，否则删掉的就是马上要被覆盖的那个文件。
        // 删除失败只计入 IO 失败、不中断：当前文件照常改名落地，源图保持原样。
        if (opt.delete_input)
        {
            if (path_equal_ci(outpath, inpath))
            {
                if (opt.verbose)
                    log_err("input kept (output overwrites it): %s\n", iu_to_utf8(inpath).c_str());
            }
            else
            {
                std::error_code ec;
                std::filesystem::remove(iu_fs_path(inpath), ec);
                if (ec)
                {
                    log_err("cannot delete input: %s\n", iu_to_utf8(inpath).c_str());
                    io_failures++;
                }
                else if (opt.verbose)
                {
                    log_err("deleted input: %s\n", iu_to_utf8(inpath).c_str());
                }
            }
        }
        // 改名成目标：同一目录内 rename，不跨盘搬运。失败时目标保持原样，临时文件保留（内容是完整
        // 产物，路径写进日志供手工恢复），该文件按 IO 失败计。
        // 目标已存在时改到它在盘上的真实名字上：否则原地覆盖会把源文件目录项的拼写改成本次 outpath
        // 的拼写（A.PNG + 同格式 → A.png），用户看到的名字被改而内容无误。
        {
            std::error_code rec;
            const path_t realname = case_variant_entry_name(outpath);
            if (!realname.empty())
                outpath = iu_fs_path_w(iu_fs_path(outpath).parent_path() / iu_fs_path(realname));
            std::filesystem::rename(iu_fs_path(tmppath), iu_fs_path(outpath), rec);
            if (rec)
            {
                log_err("temp file kept: %s\n", iu_to_utf8(tmppath).c_str());
                fail(false, "cannot write output", outpath);
                continue;
            }
        }
        // 逐文件成功行输出到 stdout（GUI 解析 " done" 后缀显示 ✔；UTF-8）
        log_out("%s -> %s done\n", iu_to_utf8(inpath).c_str(), iu_to_utf8(outpath).c_str());
        if (single_file && opt.suffix == SUFFIX_FOLDER && path_equal_ci(outpath, inpath))
            overwrote_input = inpath;

        advance_progress();
    }

    log_out("done\n");

    // 覆盖不可撤销，按四态口径在输出日志最末尾提示（只在确实原地覆盖时出现）
    if (!overwrote_input.empty())
        log_out("output overwrote the input file: %s\n", iu_to_utf8(overwrote_input).c_str());

    if (infer_failures > 0)
    {
        log_err("finished with %d inference failures\n", infer_failures);
        return EXIT_INFER;
    }
    if (io_failures > 0)
    {
        log_err("finished with %d io failures\n", io_failures);
        return EXIT_IO;
    }
    return EXIT_OK;
}

// 引擎主体：由导出面 iu_run 包裹（异常不得逃出 DLL 边界）
static int iu_run_impl(int argc, const wchar_t* const* argv)
{
    path_t inputpath;
    path_t model_id = PATHSTR("waifu2x_upconv_7_art");
    path_t models_dir = PATHSTR("models");
    bool models_dir_given = false;
    double scale_arg = 2.0;
    bool scale_given = false;
    bool width_given = false;
    bool height_given = false;
    int target_value = 0;
    bool target_is_width = true;
    path_t format = PATHSTR("jpg");
    bool format_same = false; // 工单 71：-f same —— 逐文件跟随输入格式
    int quality = 90;
    int tilesize_arg = 0;
    int gpuid_arg = -1000; // -1000 = auto
    int denoise_level = 0;
    int down_filter = RF_LANCZOS3; // 工单 42：降采样滤镜，默认 Lanczos
    SuffixMode suffix = SUFFIX_BOTH; // 四态：段落在输出文件夹名上还是产物文件名上（默认两者）
    bool delete_input = false; // 写成完整 tmp 后、改名成目标前删除
    bool sequence = false;     // 序列化重命名：产物名主干换成按自然序发的编号
    bool denoise_auto = false; // AUTO：按文件伪影估计自动选档（工单 06）
    int verbose = 0;

    setlocale(LC_ALL, "");

    for (int i = 1; i < argc; i++)
    {
        const wchar_t* a = argv[i];
        if (wcscmp(a, L"-i") == 0 && i + 1 < argc)
        {
            inputpath = argv[++i];
        }
        else if (wcscmp(a, L"-m") == 0 && i + 1 < argc)
        {
            model_id = argv[++i];
        }
        else if (wcscmp(a, L"-s") == 0 && i + 1 < argc)
        {
            scale_arg = wcstod(argv[++i], NULL);
            scale_given = true;
        }
        else if (wcscmp(a, L"--width") == 0 && i + 1 < argc)
        {
            target_value = iu_wtoi(argv[++i]);
            width_given = true;
            target_is_width = true;
        }
        else if (wcscmp(a, L"--height") == 0 && i + 1 < argc)
        {
            target_value = iu_wtoi(argv[++i]);
            height_given = true;
            target_is_width = false;
        }
        else if (wcscmp(a, L"--denoise") == 0 && i + 1 < argc)
        {
            std::wstring d = argv[++i];
            if (d == L"none") denoise_level = 0;
            else if (d == L"low") denoise_level = 1;
            else if (d == L"mid") denoise_level = 2;
            else if (d == L"high") denoise_level = 3;
            else if (d == L"auto") denoise_auto = true;
            else
            {
                log_err("invalid --denoise level (auto/none/low/mid/high)\n");
                return EXIT_PARAM;
            }
        }
        else if (wcscmp(a, L"--down-filter") == 0 && i + 1 < argc)
        {
            std::wstring df = argv[++i];
            int found = -1;
            for (int k = 0; k < kDownFilterCount; ++k)
            {
                if (df == kDownFilterNames[k])
                {
                    found = k;
                    break;
                }
            }
            if (found < 0)
            {
                log_err("invalid --down-filter (lanczos/catmullrom/bicubic/box)\n");
                return EXIT_PARAM;
            }
            down_filter = found;
        }
        else if (wcscmp(a, L"-f") == 0 && i + 1 < argc)
        {
            std::wstring f = argv[++i];
            if (f == L"same") // 工单 71：逐文件跟随输入格式
            {
                // 末次生效：`-f bad -f same` 里最后一个参数是 same，就该按 same 跑 ——
                // format 归位默认值，否则校验会拿前一个非法值报 EXIT_PARAM
                format_same = true;
                format = PATHSTR("jpg");
            }
            else
            {
                // 末次生效（与其它标量项一致）：`-f same -f jpg` 不该让后一个被静默忽略
                format_same = false;
                format = f;
            }
        }
        else if (wcscmp(a, L"-q") == 0 && i + 1 < argc)
        {
            quality = iu_wtoi(argv[++i]);
        }
        else if (wcscmp(a, L"-t") == 0 && i + 1 < argc)
        {
            tilesize_arg = iu_wtoi(argv[++i]);
        }
        else if (wcscmp(a, L"-g") == 0 && i + 1 < argc)
        {
            gpuid_arg = iu_wtoi(argv[++i]);
        }
        else if (wcscmp(a, L"--models-dir") == 0 && i + 1 < argc)
        {
            models_dir = argv[++i];
            models_dir_given = true;
        }
        else if (wcscmp(a, L"--suffix") == 0 && i + 1 < argc)
        {
            std::wstring m = argv[++i];
            if (m == L"both") suffix = SUFFIX_BOTH;
            else if (m == L"folder") suffix = SUFFIX_FOLDER;
            else if (m == L"file") suffix = SUFFIX_FILE;
            else if (m == L"none") suffix = SUFFIX_NONE;
            else
            {
                log_err("invalid --suffix value (both/folder/file/none)\n");
                return EXIT_PARAM;
            }
        }
        else if (wcscmp(a, L"--no-rename") == 0)
        {
            suffix = SUFFIX_NONE; // 与 --suffix none 同义；末次生效，与其它标量项一致
        }
        else if (wcscmp(a, L"--delete-input") == 0)
        {
            delete_input = true;
        }
        else if (wcscmp(a, L"--sequence") == 0)
        {
            sequence = true;
        }
        else if (wcscmp(a, L"-v") == 0)
        {
            verbose = 1;
        }
        else if (wcscmp(a, L"-h") == 0)
        {
            print_usage();
            return EXIT_OK;
        }
        else
        {
            log_err("unknown or incomplete argument: %s\n", iu_to_utf8(a).c_str());
            print_usage();
            return EXIT_PARAM;
        }
    }

    if (inputpath.empty())
    {
        log_err("missing -i input path\n");
        print_usage();
        return EXIT_PARAM;
    }

    // 尺寸模式三选一（规格：宽/高互斥，且与倍率互斥）
    {
        int modes = (width_given ? 1 : 0) + (height_given ? 1 : 0) + (scale_given ? 1 : 0);
        if (modes > 1)
        {
            log_err("-s, --width and --height are mutually exclusive\n");
            return EXIT_PARAM;
        }
        if ((width_given || height_given) && target_value <= 0)
        {
            log_err("invalid target size (must be > 0)\n");
            return EXIT_PARAM;
        }
    }
    bool target_mode = width_given || height_given;

    // ---- 参数校验（全部 -> EXIT_PARAM） ----
    // 工单 71：`-f same` 已在解析时置 format_same，此时 format 保持默认 jpg（不参与编码）
    if (wcscmp(format.c_str(), L"jpg") != 0 && wcscmp(format.c_str(), L"png") != 0 && wcscmp(format.c_str(), L"webp") != 0)
    {
        log_err("invalid format argument (jpg/png/webp/same)\n");
        return EXIT_PARAM;
    }

    if (quality < 0 || quality > 100)
    {
        log_err("invalid quality argument (0-100)\n");
        return EXIT_PARAM;
    }

    if (tilesize_arg != 0 && tilesize_arg < 32)
    {
        log_err("invalid tilesize argument (>=32 or 0=auto)\n");
        return EXIT_PARAM;
    }

    // ---- 模型清单 ----
    // 工单 16 / lessons §1.4：models 定位顺序 —— 显式 --models-dir > 引擎目录/models >
    // 引擎上级/models > CWD/models。exe 优先：CWD 里若有过期清单，不得压过引擎自带的清单；
    // dist 布局 models 在引擎同级，GUI 以引擎目录为工作目录启动，开发布局两者解析到同一个仓库 models/
    if (!models_dir_given)
    {
        // 候选目录由 exe 自身位置推出（不信任 CWD），与启动方式无关
        const path_t exe_dir = get_executable_directory();
        for (const path_t& cand : { exe_dir + PATHSTR("models"),
                                    exe_dir + PATHSTR("../models"),
                                    path_t(PATHSTR("models")) })
        {
            std::error_code ec;
            if (std::filesystem::exists(std::filesystem::u8path(iu_utf8_encode(cand + PATHSTR("/manifest.conf"))), ec))
            {
                models_dir = cand;
                break;
            }
        }
    }
    std::vector<ModelInfo> models;
    if (!parse_manifest(models_dir + PATHSTR("/manifest.conf"), models) || models.empty())
    {
        log_err("cannot read models/manifest.conf (searched CWD/models, engine-dir/models, engine-dir/../models)\n");
        return EXIT_PARAM;
    }

    std::string wid(model_id.begin(), model_id.end());
    const ModelInfo* mi = 0;
    for (const ModelInfo& m : models)
    {
        if (m.id == wid)
        {
            mi = &m;
            break;
        }
    }
    if (!mi)
    {
        log_err("unknown model id: %s\n", iu_to_utf8(model_id).c_str());
        return EXIT_PARAM;
    }

    if (denoise_auto)
    {
        // 工单 44：AUTO 按文件估计出的档位要直接查清单，档位不连续的模型（如 realcugan-pro
        // 只有 无/高）会在运行期落到不存在的档位，故 AUTO 要求 无/低/中/高 四档齐备
        const bool full_ladder = mi->denoise.count(0) && mi->denoise.count(1) &&
                                 mi->denoise.count(2) && mi->denoise.count(3);
        if (!full_ladder)
        {
            log_err("model %s has no full denoise ladder (AUTO requires none/low/mid/high)\n", mi->id.c_str());
            return EXIT_PARAM;
        }
        denoise_level = 0; // 具体档位按文件估计（见 run_files）
    }
    if (mi->denoise.find(denoise_level) == mi->denoise.end())
    {
        log_err("model %s does not support denoise level %d\n", mi->id.c_str(), denoise_level);
        return EXIT_PARAM;
    }

    // ---- 命名段 ----
    std::wstring wdisplay(mi->display.begin(), mi->display.end());
    wchar_t scale_seg[24];
    if (target_mode)
    {
        swprintf(scale_seg, 24, L"%dx", target_value);
    }
    else
    {
        swprintf(scale_seg, 24, L"%.1fx", scale_arg);
    }
    // 降噪段一律写解析档位（含 n0，工单 39）：无降噪（手动"无"或 AUTO 解析为 0）写 -n0，
    // 低/中/高写 -n1/2/3；直通缩放不跑模型，永不写该段
    std::wstring denoise_seg = L"-n" + std::to_wstring(denoise_level);

    const NamingSegments naming = [&] {
        NamingSegments n;
        n.display = wdisplay;
        n.denoise_seg = denoise_seg;
        n.scale_seg = scale_seg;
        return n;
    }();

    // 倍率模式：倍数合法性（清单原生倍率）
    if (!target_mode)
    {
        bool ok = false;
        for (int s : mi->scales)
        {
            if ((double)s == scale_arg)
            {
                ok = true;
                break;
            }
        }
        if (!ok)
        {
            log_err("unsupported scale %g for model %s (native:", scale_arg, mi->id.c_str());
            for (int s : mi->scales)
                log_err(" %dx", s);
            log_err(")\n");
            return EXIT_PARAM;
        }
    }
    const int run_scale = target_mode ? mi->scales.back() : (int)scale_arg;

    // ---- 收集输入文件与输出路径 ----
    bool input_is_dir = path_is_directory(inputpath);
    const bool single_file = !input_is_dir;
    // 目录 + AUTO 且各文件档位不一致时，逐文件在产物名里补 -nN（工单 39）
    bool denoise_per_file = false;

    std::vector<path_t> input_files;
    std::vector<path_t> output_files;

    auto ext_is_image = [](const path_t& ext) {
        // 工单 71：复用 encoder_of_input_extension 的扩展名集合（原先这里另拄一份）——
        // 两份手写集合的后果是只改一处时 `-f same` 拿到空编码器，静默落进 WebP 分支，
        // 写出与产物后缀不符的字节
        return !encoder_of_input_extension(ext).empty();
    };

    if (input_is_dir)
    {
        std::filesystem::path in = iu_fs_path(inputpath);

        // 递归收集（工单 05）：仅顶层文件夹重命名，内部目录结构与文件名原样镜像
        std::vector<std::pair<std::filesystem::path, std::filesystem::path>> found; // (full, rel)
        for (auto& entry : std::filesystem::recursive_directory_iterator(iu_fs_path(inputpath)))
        {
            if (!entry.is_regular_file())
                continue;
            if (!ext_is_image(get_file_extension(iu_fs_path_w(entry.path().filename()))))
                continue;
            found.push_back({entry.path(), std::filesystem::relative(entry.path(), iu_fs_path(inputpath))});
        }

        // 目录遍历顺序由文件系统决定（ext4 是按名哈希、NTFS 近似创建序）：按相对路径排序，
        // 让批处理顺序与产物命名的顺序在任何平台上都确定。
        // 序列化重命名开启时，同一目录内改按资源管理器的自然序排（编号按这个顺序发）；
        // 目录之间仍按相对路径排 —— 每个目录各自从 001 起，跨目录的先后只影响处理顺序
        std::sort(found.begin(), found.end(),
                  [sequence](const std::pair<std::filesystem::path, std::filesystem::path>& a,
                             const std::pair<std::filesystem::path, std::filesystem::path>& b) {
                      if (!sequence)
                          return a.second < b.second;
                      if (a.second.parent_path() != b.second.parent_path())
                          return a.second.parent_path() < b.second.parent_path();
                      return compare_natural(iu_fs_path_w(a.second.filename()),
                                             iu_fs_path_w(b.second.filename())) < 0;
                  });

        if (found.empty())
        {
            log_err("no matching image files (jpg/jpeg/png/webp) in: %s\n", iu_to_utf8(inputpath).c_str());
            return EXIT_PARAM;
        }

        // AUTO 的档位逐文件解析：全批一致 → 目录名写该档位、内部名不变；
        // 不一致 → 目录名写 nX、每个文件各自补 -nN（工单 39）
        // 关：目录名与产物名都不带任何段，逐文件档位只决定加载哪份权重、不进产物名，因此这一段不参与、
        // denoise_per_file 保持 false；开（文件）也要它，跑前撞车检查要用全批一致的档位段
        std::wstring dir_denoise_seg = denoise_seg;
        // 工单 71：AUTO 探测的格式参数用**本文件**的编码器（`-f same` 时跟随输入），
        // 与 run_files 的 alpha 口径一致（探测只影响 alpha 是否拍平，估计器只看 RGB）
        if (denoise_auto && suffix != SUFFIX_NONE)
        {
            auto probe_enc = [&](const path_t& p) {
                return output_format_of(p, format_same, format).enc;
            };
            int first_level = probe_denoise_level(iu_fs_path_w(found.front().first), probe_enc(iu_fs_path_w(found.front().first)));
            bool uniform = true;
            for (size_t i = 1; i < found.size() && uniform; i++)
                uniform = probe_denoise_level(iu_fs_path_w(found[i].first), probe_enc(iu_fs_path_w(found[i].first))) == first_level;

            denoise_per_file = !uniform;
            dir_denoise_seg = denoise_per_file ? L"-nX" : (L"-n" + std::to_wstring(first_level));
        }

        // 开（两者）/开（文件夹）：产物进同级输出目录（目录名带段），目录内镜像源树的相对路径；
        // 开（文件）/关：不建输出目录，产物落**源文件同目录**，段（开（文件）才有）加在文件名上。
        // 例外：后两态与「删除输入文件」合用即整树原地转换/覆盖，二次运行会把产物当输入再跑一轮
        std::error_code ec;
        const std::filesystem::path out_dir_path = in.parent_path() / iu_fs_path(iu_fs_path_w(in.filename()) + L"-(" + wdisplay + L")" + dir_denoise_seg + L"-" + scale_seg);
        // 序列化重命名的编号：每个目录（相对路径的父目录）各自从 001 起，3 位补零、
        // 超过 999 自然变 4 位；产物名主干换成本编号，源文件名不动
        std::map<std::wstring, int, OrdinalLess> sequence_counter;
        for (auto& pair : found)
        {
            input_files.push_back(iu_fs_path_w(pair.first));
            path_t stem;
            if (sequence)
            {
                stem = sequence_stem(++sequence_counter[iu_fs_path_w(pair.second.parent_path())]);
            }
            else
            {
                stem = get_file_name_without_extension(iu_fs_path_w(pair.second.filename()));
            }
            if (suffix_uses_folder(suffix))
                output_files.push_back(iu_fs_path_w(out_dir_path / pair.second.parent_path() / iu_fs_path(stem)));
            else
                output_files.push_back(iu_fs_path_w(pair.first.parent_path() / iu_fs_path(stem)));
        }

        // 跑前撞车守卫（**每条命名路径都适用**）：
        //   ① 产物撞上**同批的另一个输入文件** —— 产物落源目录的那几态 + 同目录 a.png + a.jpg 配 -f jpg：
        //      a.png 的产物就是 a.jpg 本身
        //   ② 两个产物彼此同路 —— a.png + a.jpeg 配 -f jpg（两个 stem 都是 a）、
        //      a.png + a.jpg 配 -f webp（都产出 a.webp）、开后缀段的 1.jpg + 1.png 配 -f jpg
        // 不拒的后果都是静默的：某个文件从未被处理（原内容被先写出的产物盖掉），或读到上一文件刚写出的
        // 产物而被放大两轮；配 --delete-input 更会连源图一起消失（两张源图都被删、只剩一张产物）。
        // 与工单 58 的「产物覆盖自己」（同一文件）不冲突：那种情况 index 相同，两条都放行。
        // 逐文件档位（AUTO 档位不一致）时产物名在运行期才定 → 这一路跳过跑前检查，由 run_files 的
        // 运行期守卫兜住（同一个 canonical 键，产物撞输入与产物撞产物两条都判）；开（文件）在目标尺寸
        // 模式下逐文件才知走 SR 还是直通缩放（产物名分别是 -(模型名)-… 与 -(Resize)-…），跑前同样算不准。
        // 门控与运行期守卫同一判据（collision_guard_enabled）：「序列化重命名」与「删除输入文件」
        // 都关时才生效；任一打开即用户主动进入命名/清理模式，产物一律覆盖、不报错
        const bool collision_guard = collision_guard_enabled(sequence, delete_input);
        const bool name_unknown_before_run = denoise_per_file || (suffix == SUFFIX_FILE && target_mode);
        if (collision_guard && !name_unknown_before_run)
        {
            // 判据与 run_files 共用 product_denoise_seg；档位段取本批口径
            // （非 AUTO 用 denoise_seg，AUTO 全批同档用 dir_denoise_seg）
            const std::wstring guard_denoise_seg = product_denoise_seg(
                suffix, false, denoise_per_file, denoise_auto ? dir_denoise_seg : denoise_seg);
            auto product_path = [&](size_t i) {
                return dir_product_path(output_files[i], naming, guard_denoise_seg,
                                        output_format_of(input_files[i], format_same, format).ext,
                                        false, suffix);
            };
            std::map<std::wstring, size_t, OrdinalLess> by_input;
            for (size_t i = 0; i < input_files.size(); i++)
                by_input[canonical_path_key(input_files[i])] = i;
            std::map<std::wstring, size_t, OrdinalLess> by_product;
            for (size_t i = 0; i < output_files.size(); i++)
            {
                const std::wstring key = canonical_path_key(product_path(i));
                auto in_it = by_input.find(key);
                auto out_it = by_product.find(key);
                if (in_it != by_input.end() && in_it->second != i)
                {
                    log_err("output of %s would overwrite another input file: %s\n",
                            iu_to_utf8(input_files[i]).c_str(), iu_to_utf8(input_files[in_it->second]).c_str());
                    log_err("(with --suffix none/file the output keeps the original name, so same-name files of\n"
                            " different extensions in one directory collide; use --suffix both/folder or split them)\n");
                    return EXIT_PARAM;
                }
                if (out_it != by_product.end() && out_it->second != i)
                {
                    log_err("outputs of %s and %s are the same file: %s\n",
                            iu_to_utf8(input_files[i]).c_str(), iu_to_utf8(input_files[out_it->second]).c_str(),
                            iu_to_utf8(product_path(i)).c_str());
                    log_err("(two inputs with the same name but different extensions write to one output;\n"
                            " use \"-f same\" to keep each input's own format, or split them)\n");
                    return EXIT_PARAM;
                }
                by_product[key] = i;
            }
        }

        if (suffix_uses_folder(suffix))
        {
            std::filesystem::create_directories(out_dir_path, ec);
            if (ec)
            {
                log_err("cannot create output directory: %s (%s)\n", iu_to_utf8(iu_fs_path_w(out_dir_path)).c_str(), ec.message().c_str());
                return EXIT_IO;
            }
            for (auto& pair : found)
                std::filesystem::create_directories(out_dir_path / pair.second.parent_path(), ec);
        }
    }
    else
    {
        if (!ext_is_image(get_file_extension(inputpath)))
        {
            log_err("unsupported input file type: %s (jpg/jpeg/png/webp)\n", iu_to_utf8(inputpath).c_str());
            return EXIT_PARAM;
        }
        if (!filepath_is_readable(inputpath))
        {
            log_err("input file not readable: %s\n", iu_to_utf8(inputpath).c_str());
            return EXIT_IO;
        }
        input_files.push_back(inputpath);
        // 单文件输出路径在 run_files 内按实际路径（SR / 直通缩放）生成
    }

    // ---- ncnn 初始化 ----
    ncnn::create_gpu_instance();

    int gpuid = gpuid_arg;
    if (gpuid == -1000)
    {
        gpuid = ncnn::get_default_gpu_index();
    }

    int gpu_count = ncnn::get_gpu_count();
    if (gpuid != -1 && (gpuid < 0 || gpuid >= gpu_count))
    {
        log_err("invalid gpu device (available: %d)\n", gpu_count);
        ncnn::destroy_gpu_instance();
        return EXIT_PARAM;
    }

    if (gpuid != -1 && gpu_count == 0)
    {
        log_err("warning: no Vulkan device found, falling back to CPU\n");
        gpuid = -1;
    }

    // tile 自动策略（按显存堆预算分档，镜像各官方引擎）
    int tilesize = tilesize_arg;
    if (tilesize == 0)
    {
        if (gpuid == -1)
        {
            tilesize = 400;
        }
        else
        {
            uint32_t heap_budget = ncnn::get_gpu_device(gpuid)->get_heap_budget();
            if (mi->tileauto == "cunet")
            {
                if (heap_budget > 2600)
                    tilesize = 400;
                else if (heap_budget > 740)
                    tilesize = 200;
                else if (heap_budget > 250)
                    tilesize = 100;
                else
                    tilesize = 32;
            }
            else if (mi->tileauto == "realesrgan")
            {
                if (heap_budget > 1900)
                    tilesize = 200;
                else if (heap_budget > 550)
                    tilesize = 100;
                else if (heap_budget > 190)
                    tilesize = 64;
                else
                    tilesize = 32;
            }
            else // upconv | cugan
            {
                if (heap_budget > 1900)
                    tilesize = 400;
                else if (heap_budget > 550)
                    tilesize = 200;
                else if (heap_budget > 190)
                    tilesize = 100;
                else
                    tilesize = 32;
            }
        }
    }

    int cpu_count = std::max(1, ncnn::get_cpu_count());
    int num_threads = gpuid == -1 ? std::min(4, cpu_count) : 1;

    if (verbose)
    {
        log_err("model: %s arch=%s denoise=%d tilesize=%d gpuid=%d mode=%s\n",
                mi->id.c_str(), mi->arch.c_str(), denoise_level, tilesize, gpuid,
                target_mode ? "target" : "ratio");
        log_err("down-filter: %s\n", iu_to_utf8(kDownFilterNames[down_filter]).c_str());
    }

    // ---- 按架构创建引擎并执行循环 ----
    int rc = EXIT_OK;

    const RunOptions opt = [&] {
        RunOptions o;
        o.format = format;
        o.format_same = format_same;
        o.quality = quality;
        o.run_scale = run_scale;
        o.target_mode = target_mode;
        o.target_value = target_value;
        o.target_is_width = target_is_width;
        o.down_filter = down_filter;
        o.tilesize = tilesize;
        o.denoise_auto = denoise_auto;
        o.verbose = verbose != 0;
        o.suffix = suffix;
        o.delete_input = delete_input;
        o.sequence = sequence;
        return o;
    }();
    auto run_arch = [&](auto* engine) {
        return run_files(engine, models_dir, *mi, input_files, output_files, single_file, denoise_per_file,
                         denoise_level, naming, opt);
    };

    if (mi->arch == "waifu2x")
    {
        Waifu2xEngine engine(gpuid, num_threads);
        rc = run_arch(&engine);
    }
    else if (mi->arch == "cugan")
    {
        CuganEngine engine(gpuid, num_threads, mi->pro);
        rc = run_arch(&engine);
    }
    else // rrdb | compact
    {
        RealesrganEngine engine(gpuid, num_threads);
        rc = run_arch(&engine);
    }

    ncnn::destroy_gpu_instance();
    return rc;
}

IU_API int iu_run(int argc, const wchar_t* const* argv, iu_line_cb out_cb, iu_line_cb err_cb, void* user)
{
    g_out_cb = out_cb;
    g_err_cb = err_cb;
    g_user = user;
    // 模型实现（waifu2x / realcugan / realesrgan）的输出也走宿主回调，不再直写 stderr（lessons §1.3）；
    // 每次 iu_run 都重设，避免悬空回调
    iu_set_log_sink(g_err_cb, g_user);

    // 异常不得逃出导出面：std::filesystem 在权限拒绝 / 内存不足时会抛异常，
    // 逃出 DLL 边界即 std::terminate，会把宿主 GUI 一起带走
    try
    {
        return iu_run_impl(argc, argv);
    }
    catch (const std::filesystem::filesystem_error& e)
    {
        log_err("filesystem error: %s\n", e.what());
        return EXIT_IO;
    }
    catch (const std::exception& e)
    {
        log_err("internal error: %s\n", e.what());
        return EXIT_INFER;
    }
    catch (...)
    {
        log_err("internal error: unknown exception\n");
        return EXIT_INFER;
    }
}
