// image-upscale 引擎 CLI（工单 01 基础 + 03 模型清单/降噪 + 02 尺寸模式）
// 命令面、命名规则、格式/质量控制为本项目原创；
// tiled 推理内核适配自 nihui/waifu2x-ncnn-vulkan、realcugan-ncnn-vulkan、
// Real-ESRGAN-ncnn-vulkan（均 MIT，见 NOTICE.md）
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <map>
#include <string>
#include <vector>
#include <algorithm>
#include <clocale>
#include <filesystem>

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

#if _WIN32
#define PATH_MAIN wmain
#else
#define PATH_MAIN main
#endif

static void print_usage()
{
    fprintf(stdout, "Usage: image-upscale -i input-path [options]...\n\n");
    fprintf(stdout, "  -i input-path        input image (jpg/jpeg/png/webp) or directory\n");
    fprintf(stdout, "  -m model-id          model id from models/manifest.conf (default: upconv7-anime)\n");
    fprintf(stdout, "  -s scale             ratio mode: native scale of the model (default: 2.0)\n");
    fprintf(stdout, "  --width N            target-size mode: target width (exclusive with -s/--height)\n");
    fprintf(stdout, "  --height N           target-size mode: target height (exclusive with -s/--width)\n");
    fprintf(stdout, "  --denoise level      none/low/mid/high (default: none; model must support it)\n");
    fprintf(stdout, "  -f format            output image format jpg/png/webp (default: jpg)\n");
    fprintf(stdout, "  -q quality           output quality 0-100 for jpg/webp (default: 90)\n");
    fprintf(stdout, "  -t tile-size         tile size (>=32/0=auto, default: 0)\n");
    fprintf(stdout, "  -g gpu-id            gpu device (-1=cpu, default: auto)\n");
    fprintf(stdout, "  --models-dir path    models directory (default: models)\n");
    fprintf(stdout, "  -v                   verbose output\n");
    fprintf(stdout, "  -h                   show this help\n");
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
};

static bool parse_manifest(const std::string& path, std::vector<ModelInfo>& out)
{
    FILE* fp = fopen(path.c_str(), "rb");
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
    CuganEngine(int gpuid, int num_threads) : impl(gpuid, false, num_threads) {}
    int load_files(const std::wstring& p, const std::wstring& b) override { return impl.load(p, b); }
    int process(const ncnn::Mat& in, ncnn::Mat& out) const override { return impl.process(in, out); }
    void configure(int scale, int denoise_level, int tilesize, int prepadding) override
    {
        impl.noise = denoise_level;
        impl.scale = scale;
        impl.tilesize = tilesize;
        impl.prepadding = prepadding;
        impl.syncgap = 3;
    }
};

struct RealesrganEngine : IEngine
{
    RealESRGAN impl;
    RealesrganEngine(int gpuid) : impl(gpuid, false) {}
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
    FILE* fp = _wfopen(path.c_str(), L"wb");
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

// 高质量等比缩放（Catmull-Rom；通道数 1/3/4；输出为 uchar 交错布局）
static bool resize_rgb(const ncnn::Mat& src, ncnn::Mat& dst, int out_w, int out_h, int channels)
{
    stbir_pixel_layout layout = (stbir_pixel_layout)channels;
    dst.create(out_w, out_h, (size_t)channels, channels); // 与引擎 outimage 约定一致（编码器以 elempack 为通道数）
    return stbir_resize_uint8_linear((const unsigned char*)src.data, src.w, src.h, src.w * channels,
        (unsigned char*)dst.data, out_w, out_h, out_w * channels, layout) != 0;
}

// 目标尺寸模式的原生倍率选择：≥ 比例的最小档，不足取最大档
static int pick_native_scale(const ModelInfo& mi, double ratio)
{
    int best = 0;
    for (int s : mi.scales)
    {
        if ((double)s >= ratio && (best == 0 || s < best))
            best = s;
    }
    if (best == 0)
        best = *std::max_element(mi.scales.begin(), mi.scales.end());
    return best;
}

// ---- 模型文件解析（按架构与倍数/降噪档） ----
static void resolve_model_files(const std::wstring& models_dir, const ModelInfo& mi, int scale, int denoise_level,
                                path_t& parampath, path_t& binpath, int& prepadding)
{
    path_t model_dir = models_dir + PATHSTR("/") + widen(mi.dir);
    const std::string& token = mi.denoise.at(denoise_level);

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
}

// 单文件输出的命名（工单 02 命名规则）
// SR 路径：A-(模型名)-[nN-]<倍率|尺寸>；直通缩放：A-(Resize)-<尺寸>
static path_t single_file_outpath(const std::filesystem::path& in, const std::wstring& display,
                                  const std::wstring& denoise_seg, const std::wstring& scale_seg,
                                  const std::wstring& ext, bool direct_resize)
{
    if (direct_resize)
        return in.parent_path() / (in.stem().wstring() + L"-(Resize)-" + scale_seg + L"." + ext);
    return in.parent_path() / (in.stem().wstring() + L"-(" + display + L")" + denoise_seg + L"-" + scale_seg + L"." + ext);
}

// 解码 → 推理/直通缩放 → 编码 循环（顺序流水，进度行输出到 stdout）
// 引擎类只需提供 process(in, out) const；模板避免多套重复代码
template <typename Engine>
static int run_files(Engine* engine, const std::wstring& models_dir, const ModelInfo& mi, int denoise_level,
                     const std::vector<path_t>& input_files,
                     const std::vector<path_t>& output_files, const path_t& format,
                     int quality, int run_scale, bool target_mode, int target_value,
                     bool target_is_width, bool single_file, const std::wstring& wext,
                     const std::wstring& wdisplay, const std::wstring& denoise_seg,
                     const std::wstring& scale_seg, int tilesize, bool denoise_auto, bool verbose)
{
    const int total = (int)input_files.size();
    int done = 0;
    int infer_failures = 0;
    int io_failures = 0;

    auto advance_progress = [&]() {
        done++;
        printf("progress %d/%d\n", done, total);
        fflush(stdout);
    };
    auto fail = [&](bool inference_failure, const char* msg, const path_t& path) {
        fprintf(stderr, "%s: %ls\n", msg, path.c_str());
        if (inference_failure)
            infer_failures++;
        else
            io_failures++;
        advance_progress();
    };

    // 当前已加载的模型倍数（尺寸模式可能按文件切换倍数 → 变更时重载）
    int loaded_scale = -1;
    path_t cur_param, cur_bin;
    int cur_prepad = 0;

    for (int i = 0; i < total; i++)
    {
        const path_t& inpath = input_files[i];

        // 解码
        unsigned char* pixeldata = 0;
        int w = 0;
        int h = 0;
        int c = 0;
        {
            FILE* fp = _wfopen(inpath.c_str(), L"rb");
            if (!fp)
            {
                fail(false, "cannot open input", inpath);
                continue;
            }

            fseek(fp, 0, SEEK_END);
            long length = ftell(fp);
            rewind(fp);
            unsigned char* filedata = (unsigned char*)malloc(length);
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

        // alpha 处理（工单 04）：PNG/WebP 输出保留并同步放大；JPG 输出与白底合成
        bool has_alpha = false;
        std::vector<unsigned char> alpha_src;
        std::vector<unsigned char> alpha_merged; // 工单 15：生存期必须覆盖合并→编码→写盘（旧代码块作用域导致 use-after-free）
        if (c == 4 && format != PATHSTR("jpg"))
        {
            has_alpha = true;
            alpha_src.resize((size_t)w * h);
            for (int i = 0; i < w * h; i++)
                alpha_src[i] = pixeldata[(size_t)i * 4 + 3];
            unsigned char* rgb = (unsigned char*)malloc((size_t)w * h * 3);
            if (!rgb)
            {
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
                fail(false, "out of memory", inpath);
                continue;
            }
            pixeldata = rgb;
            c = 3;
        }

        if (verbose)
        {
            fprintf(stderr, "loaded %ls (%dx%d)\n", inpath.c_str(), w, h);
        }

        // 目标尺寸模式的每文件决策：指定维度 ≥ 原图 → 超分；< 原图 → 直通缩放
        // AUTO：按当前文件伪影估计规范档位（单文件命名与模型变体都使用解析结果）
        int file_denoise = denoise_level;
        if (denoise_auto)
        {
            file_denoise = estimate_denoise_level(pixeldata, w, h);
            if (verbose)
                fprintf(stderr, "denoise: auto resolved level=%d\n", file_denoise);
        }

        bool use_engine = true;
        int file_scale = run_scale;
        if (target_mode)
        {
            const int orig_dim = target_is_width ? w : h;
            if (target_value < orig_dim)
            {
                use_engine = false;
            }
            else
            {
                const double ratio = (double)target_value / (double)orig_dim;
                file_scale = pick_native_scale(mi, ratio);
            }
        }

        // 输出路径（单文件按 SR/直通分别命名；文件夹预构建）
        std::wstring file_denoise_seg = denoise_auto && file_denoise > 0
            ? (L"-n" + std::to_wstring(file_denoise))
            : denoise_seg;
        path_t outpath;
        if (single_file)
        {
            std::filesystem::path in(inpath);
            outpath = single_file_outpath(in, wdisplay, file_denoise_seg, scale_seg, wext, !use_engine);
        }
        else
        {
            outpath = output_files[i];
        }

        ncnn::Mat outimage;
        if (use_engine)
        {
            // 尺寸模式按文件倍数重载模型（倍率模式 loaded_scale 恒定）
            if (file_scale != loaded_scale || (denoise_auto && file_denoise != denoise_level))
            {
                resolve_model_files(models_dir, mi, file_scale, file_denoise, cur_param, cur_bin, cur_prepad);
                if (engine->load_files(cur_param, cur_bin) != 0)
                {
                    fail(true, "model load failed", inpath);
                    free(pixeldata);
                    continue;
                }
                loaded_scale = file_scale;
                if (verbose)
                {
                    fprintf(stderr, "engine loaded scale=%dx prepad=%d\n", file_scale, cur_prepad);
                }
            }
            engine->configure(file_scale, file_denoise, tilesize, cur_prepad);

            ncnn::Mat inimage(w, h, (void*)pixeldata, (size_t)3, 3);
            ncnn::Mat native_out(w * file_scale, h * file_scale, (size_t)3, 3);
            int pre = engine->process(inimage, native_out);
            free(pixeldata);

            if (pre != 0)
            {
                fail(true, "inference failed", inpath);
                continue;
            }

            if (!target_mode)
            {
                outimage = native_out;
            }
            else
            {
                // 精确 resize 到目标（宽/高按指定维度，另一维度等比）
                int exact_w, exact_h;
                if (target_is_width)
                {
                    exact_w = target_value;
                    exact_h = std::max(1, (int)((double)h * target_value / w + 0.5));
                }
                else
                {
                    exact_h = target_value;
                    exact_w = std::max(1, (int)((double)w * target_value / h + 0.5));
                }
                if (native_out.w == exact_w && native_out.h == exact_h)
                {
                    outimage = native_out;
                }
                else if (!resize_rgb(native_out, outimage, exact_w, exact_h, 3))
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
            if (target_is_width)
            {
                exact_w = target_value;
                exact_h = std::max(1, (int)((double)h * target_value / w + 0.5));
            }
            else
            {
                exact_h = target_value;
                exact_w = std::max(1, (int)((double)w * target_value / h + 0.5));
            }
            ncnn::Mat inimage(w, h, (void*)pixeldata, (size_t)3, 3);
            if (!resize_rgb(inimage, outimage, exact_w, exact_h, 3))
            {
                fail(false, "resize failed", inpath);
                free(pixeldata);
                continue;
            }
            free(pixeldata);
        }

        // alpha 合成（RGB 超分结果 + 同步放大的 alpha → RGBA）
        if (has_alpha)
        {
            ncnn::Mat alpha_in(w, h, (void*)alpha_src.data(), (size_t)1, 1);
            ncnn::Mat alpha_out;
            if (!resize_rgb(alpha_in, alpha_out, outimage.w, outimage.h, 1))
            {
                fail(false, "resize failed", inpath);
                continue;
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

        // 编码（按输出格式；质量参数作用于 jpg/webp）
        bool save_ok = false;
        if (format == PATHSTR("jpg"))
        {
            MemBuffer buf;
            if (stbi_write_jpg_to_func(stb_write_callback, &buf, outimage.w, outimage.h, outimage.elempack, outimage.data, quality))
            {
                save_ok = write_file_wide(outpath, buf.data.data(), buf.data.size());
            }
        }
        else if (format == PATHSTR("png"))
        {
            MemBuffer buf;
            if (stbi_write_png_to_func(stb_write_callback, &buf, outimage.w, outimage.h, outimage.elempack, outimage.data, outimage.w * outimage.elempack))
            {
                save_ok = write_file_wide(outpath, buf.data.data(), buf.data.size());
            }
        }
        else // webp
        {
            save_ok = webp_save(outpath.c_str(), outimage.w, outimage.h, outimage.elempack, (const unsigned char*)outimage.data, (float)quality) == 1;
        }

        if (!save_ok)
        {
            fail(false, "encode image failed", outpath);
            continue;
        }
        if (verbose)
        {
            fprintf(stderr, "%ls -> %ls done\n", inpath.c_str(), outpath.c_str());
        }

        advance_progress();
    }

    printf("done\n");
    fflush(stdout);

    if (infer_failures > 0)
    {
        fprintf(stderr, "finished with %d inference failures\n", infer_failures);
        return EXIT_INFER;
    }
    if (io_failures > 0)
    {
        fprintf(stderr, "finished with %d io failures\n", io_failures);
        return EXIT_IO;
    }
    return EXIT_OK;
}

int PATH_MAIN(int argc, wchar_t** argv)
{
    path_t inputpath;
    path_t model_id = PATHSTR("upconv7-anime");
    path_t models_dir = PATHSTR("models");
    double scale_arg = 2.0;
    bool scale_given = false;
    bool width_given = false;
    bool height_given = false;
    int target_value = 0;
    bool target_is_width = true;
    path_t format = PATHSTR("jpg");
    int quality = 90;
    int tilesize_arg = 0;
    int gpuid_arg = -1000; // -1000 = auto
    int denoise_level = 0; // 0=无 1=低 2=中 3=高
    bool denoise_auto = false; // AUTO：按文件伪影估计自动选档（工单 06）
    int verbose = 0;

    setlocale(LC_ALL, "");

    for (int i = 1; i < argc; i++)
    {
        wchar_t* a = argv[i];
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
            target_value = _wtoi(argv[++i]);
            width_given = true;
            target_is_width = true;
        }
        else if (wcscmp(a, L"--height") == 0 && i + 1 < argc)
        {
            target_value = _wtoi(argv[++i]);
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
                fprintf(stderr, "invalid --denoise level (auto/none/low/mid/high)\n");
                return EXIT_PARAM;
            }
        }
        else if (wcscmp(a, L"-f") == 0 && i + 1 < argc)
        {
            format = argv[++i];
        }
        else if (wcscmp(a, L"-q") == 0 && i + 1 < argc)
        {
            quality = _wtoi(argv[++i]);
        }
        else if (wcscmp(a, L"-t") == 0 && i + 1 < argc)
        {
            tilesize_arg = _wtoi(argv[++i]);
        }
        else if (wcscmp(a, L"-g") == 0 && i + 1 < argc)
        {
            gpuid_arg = _wtoi(argv[++i]);
        }
        else if (wcscmp(a, L"--models-dir") == 0 && i + 1 < argc)
        {
            models_dir = argv[++i];
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
            fprintf(stderr, "unknown or incomplete argument: %ls\n", a);
            print_usage();
            return EXIT_PARAM;
        }
    }

    if (inputpath.empty())
    {
        fprintf(stderr, "missing -i input path\n");
        print_usage();
        return EXIT_PARAM;
    }

    // 尺寸模式三选一（规格：宽/高互斥，且与倍率互斥）
    {
        int modes = (width_given ? 1 : 0) + (height_given ? 1 : 0) + (scale_given ? 1 : 0);
        if (modes > 1)
        {
            fprintf(stderr, "-s, --width and --height are mutually exclusive\n");
            return EXIT_PARAM;
        }
        if ((width_given || height_given) && target_value <= 0)
        {
            fprintf(stderr, "invalid target size (must be > 0)\n");
            return EXIT_PARAM;
        }
    }
    bool target_mode = width_given || height_given;

    // ---- 参数校验（全部 -> EXIT_PARAM） ----
    if (wcscmp(format.c_str(), L"jpg") != 0 && wcscmp(format.c_str(), L"png") != 0 && wcscmp(format.c_str(), L"webp") != 0)
    {
        fprintf(stderr, "invalid format argument (jpg/png/webp)\n");
        return EXIT_PARAM;
    }

    if (quality < 0 || quality > 100)
    {
        fprintf(stderr, "invalid quality argument (0-100)\n");
        return EXIT_PARAM;
    }

    if (tilesize_arg != 0 && tilesize_arg < 32)
    {
        fprintf(stderr, "invalid tilesize argument (>=32 or 0=auto)\n");
        return EXIT_PARAM;
    }

    // ---- 模型清单 ----
    std::vector<ModelInfo> models;
    if (!parse_manifest("models/manifest.conf", models) || models.empty())
    {
        fprintf(stderr, "cannot read models/manifest.conf (run from the app directory?)\n");
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
        fprintf(stderr, "unknown model id: %ls\n", model_id.c_str());
        return EXIT_PARAM;
    }

    if (denoise_auto)
    {
        bool any_level = mi->denoise.count(1) || mi->denoise.count(2) || mi->denoise.count(3);
        if (!any_level)
        {
            fprintf(stderr, "model %s does not support denoise (cannot use AUTO)\n", mi->id.c_str());
            return EXIT_PARAM;
        }
        denoise_level = 0; // 具体档位按文件估计（见 run_files）
    }
    if (mi->denoise.find(denoise_level) == mi->denoise.end())
    {
        fprintf(stderr, "model %s does not support denoise level %d\n", mi->id.c_str(), denoise_level);
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
    std::wstring denoise_seg = denoise_level > 0 ? (L"-n" + std::to_wstring(denoise_level)) : L"";

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
            fprintf(stderr, "unsupported scale %g for model %s (native:", scale_arg, mi->id.c_str());
            for (int s : mi->scales)
                fprintf(stderr, " %dx", s);
            fprintf(stderr, ")\n");
            return EXIT_PARAM;
        }
    }
    const int run_scale = target_mode ? mi->scales.back() : (int)scale_arg;

    // ---- 收集输入文件与输出路径 ----
    std::wstring wext = format;
    bool input_is_dir = path_is_directory(inputpath);
    const bool single_file = !input_is_dir;

    std::vector<path_t> input_files;
    std::vector<path_t> output_files;

    auto ext_is_image = [](const path_t& ext) {
        path_t e = ext;
        std::transform(e.begin(), e.end(), e.begin(), ::towlower);
        return e == PATHSTR("jpg") || e == PATHSTR("jpeg") || e == PATHSTR("png") || e == PATHSTR("webp");
    };

    if (input_is_dir)
    {
        std::filesystem::path in(inputpath);
        std::filesystem::path out_dir_path = in.parent_path() / (in.filename().wstring() + L"-(" + wdisplay + L")" + denoise_seg + L"-" + scale_seg);
        path_t output_dir = out_dir_path.wstring();

        std::error_code ec;
        std::filesystem::create_directories(out_dir_path, ec);
        if (ec)
        {
            fprintf(stderr, "cannot create output directory: %ls (%s)\n", output_dir.c_str(), ec.message().c_str());
            return EXIT_IO;
        }

        // 递归收集（工单 05）：仅顶层文件夹重命名，内部目录结构与文件名原样镜像
        std::vector<std::pair<std::filesystem::path, std::filesystem::path>> found; // (full, rel)
        for (auto& entry : std::filesystem::recursive_directory_iterator(inputpath))
        {
            if (!entry.is_regular_file())
                continue;
            if (!ext_is_image(get_file_extension(entry.path().filename().wstring())))
                continue;
            found.push_back({entry.path(), std::filesystem::relative(entry.path(), inputpath)});
        }

        for (auto& pair : found)
        {
            const std::filesystem::path& full_fs = pair.first;
            const std::filesystem::path& rel_path = pair.second;
            input_files.push_back(full_fs.wstring());
            std::filesystem::create_directories(out_dir_path / rel_path.parent_path(), ec);
            path_t stem = get_file_name_without_extension(rel_path.filename().wstring());
            output_files.push_back((out_dir_path / rel_path.parent_path() / (stem + L'.' + wext)).wstring());
        }

        if (input_files.empty())
        {
            fprintf(stderr, "no matching image files (jpg/jpeg/png/webp) in: %ls\n", inputpath.c_str());
            return EXIT_PARAM;
        }
    }
    else
    {
        if (!ext_is_image(get_file_extension(inputpath)))
        {
            fprintf(stderr, "unsupported input file type: %ls (jpg/jpeg/png/webp)\n", inputpath.c_str());
            return EXIT_PARAM;
        }
        if (!filepath_is_readable(inputpath))
        {
            fprintf(stderr, "input file not readable: %ls\n", inputpath.c_str());
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
        fprintf(stderr, "invalid gpu device (available: %d)\n", gpu_count);
        ncnn::destroy_gpu_instance();
        return EXIT_PARAM;
    }

    if (gpuid != -1 && gpu_count == 0)
    {
        fprintf(stderr, "warning: no Vulkan device found, falling back to CPU\n");
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
        fprintf(stderr, "model: %s arch=%s denoise=%d tilesize=%d gpuid=%d mode=%s\n",
                mi->id.c_str(), mi->arch.c_str(), denoise_level, tilesize, gpuid,
                target_mode ? "target" : "ratio");
    }

    // ---- 按架构创建引擎并执行循环 ----
    int rc = EXIT_OK;

    if (mi->arch == "waifu2x")
    {
        Waifu2xEngine engine(gpuid, num_threads);
        rc = run_files(&engine, models_dir, *mi, denoise_level, input_files, output_files, format,
                       quality, run_scale, target_mode, target_value, target_is_width,
                       single_file, wext, wdisplay, denoise_seg, scale_seg, tilesize, denoise_auto, verbose);
    }
    else if (mi->arch == "cugan")
    {
        CuganEngine engine(gpuid, num_threads);
        rc = run_files(&engine, models_dir, *mi, denoise_level, input_files, output_files, format,
                       quality, run_scale, target_mode, target_value, target_is_width,
                       single_file, wext, wdisplay, denoise_seg, scale_seg, tilesize, denoise_auto, verbose);
    }
    else // rrdb | compact
    {
        RealesrganEngine engine(gpuid);
        rc = run_files(&engine, models_dir, *mi, denoise_level, input_files, output_files, format,
                       quality, run_scale, target_mode, target_value, target_is_width,
                       single_file, wext, wdisplay, denoise_seg, scale_seg, tilesize, denoise_auto, verbose);
    }

    ncnn::destroy_gpu_instance();
    return rc;
}
