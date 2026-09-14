// image-upscale 引擎 CLI（工单 01 基础 + 工单 03 模型清单/降噪映射）
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
#include "stb_image.h"
#include "stb_image_write.h"
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
    fprintf(stdout, "  -s scale             upscale ratio, must be a native scale of the model (default: 2.0)\n");
    fprintf(stdout, "  --denoise level      none/low/mid/high (default: none; model must support it)\n");
    fprintf(stdout, "  -f format            output image format jpg/png/webp (default: jpg)\n");
    fprintf(stdout, "  -q quality           output quality 0-100 for jpg/webp (default: 90)\n");
    fprintf(stdout, "  -t tile-size         tile size (>=32/0=auto, default: 0)\n");
    fprintf(stdout, "  -g gpu-id            gpu device (-1=cpu, default: auto)\n");
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
        // 去掉 BOM/换行
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
            // "prepad <n>"（单倍数模型）或 "prepad <scale> <n>"（cugan）
            size_t sp2 = val.find(' ');
            if (sp2 == std::string::npos)
            {
                // 填充到所有已声明倍数
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
    {
        free(pixeldata);
        return NULL;
    }
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
    free(pixeldata);
    return rgb;
}

// ASCII → 宽字符（清单 id/变体 token 均为 ASCII，足够）
static std::wstring widen(const std::string& s)
{
    return std::wstring(s.begin(), s.end());
}

// 解码 -> 推理 -> 编码 循环（顺序流水，进度行输出到 stdout）
// 引擎类只需提供 process(in, out) const；模板避免三套重复代码
template <typename Engine>
static int run_files(Engine* engine, const std::vector<path_t>& input_files,
                     const std::vector<path_t>& output_files, const path_t& format,
                     int quality, int scale, bool verbose)
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

    for (int i = 0; i < total; i++)
    {
        const path_t& inpath = input_files[i];
        const path_t& outpath = output_files[i];

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

        // 工单 04 前：alpha 拍平白底，全链路 3 通道
        if (c == 4)
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
            // 灰度（可能带 alpha）：转 RGB，带 alpha 时拍平白底
            unsigned char* rgb = (unsigned char*)malloc((size_t)w * h * 3);
            for (int p = 0; p < w * h; p++)
            {
                const unsigned char* px = pixeldata + (size_t)p * c;
                unsigned char* out = rgb + (size_t)p * 3;
                int a = c == 2 ? px[1] : 255;
                for (int ch = 0; ch < 3; ch++)
                    out[ch] = (unsigned char)((px[0] * a + 255 * (255 - a) + 127) / 255);
            }
            free(pixeldata);
            pixeldata = rgb;
            c = 3;
        }

        if (verbose)
        {
            fprintf(stderr, "loaded %ls (%dx%d)\n", inpath.c_str(), w, h);
        }

        // 推理
        ncnn::Mat inimage(w, h, (void*)pixeldata, (size_t)3, 3);
        ncnn::Mat outimage(w * scale, h * scale, (size_t)3, 3);
        int pre = engine->process(inimage, outimage);
        free(pixeldata);

        if (pre != 0)
        {
            fail(true, "inference failed", inpath);
            continue;
        }

        // 编码（按输出格式；质量参数作用于 jpg/webp）
        bool save_ok = false;
        if (format == PATHSTR("jpg"))
        {
            MemBuffer buf;
            if (stbi_write_jpg_to_func(stb_write_callback, &buf, outimage.w, outimage.h, 3, outimage.data, quality))
            {
                save_ok = write_file_wide(outpath, buf.data.data(), buf.data.size());
            }
        }
        else if (format == PATHSTR("png"))
        {
            MemBuffer buf;
            if (stbi_write_png_to_func(stb_write_callback, &buf, outimage.w, outimage.h, 3, outimage.data, outimage.w * 3))
            {
                save_ok = write_file_wide(outpath, buf.data.data(), buf.data.size());
            }
        }
        else // webp
        {
            save_ok = webp_save(outpath.c_str(), outimage.w, outimage.h, 3, (const unsigned char*)outimage.data, (float)quality) == 1;
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
    double scale_arg = 2.0;
    path_t format = PATHSTR("jpg");
    int quality = 90;
    int tilesize_arg = 0;
    int gpuid_arg = -1000; // -1000 = auto
    int denoise_level = 0; // 0=无 1=低 2=中 3=高（AUTO 在工单 06）
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
        }
        else if (wcscmp(a, L"--denoise") == 0 && i + 1 < argc)
        {
            std::wstring d = argv[++i];
            if (d == L"none") denoise_level = 0;
            else if (d == L"low") denoise_level = 1;
            else if (d == L"mid") denoise_level = 2;
            else if (d == L"high") denoise_level = 3;
            else
            {
                fprintf(stderr, "invalid --denoise level (none/low/mid/high)\n");
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

    const ModelInfo* mi = 0;
    for (const ModelInfo& m : models)
    {
        std::string wid(model_id.begin(), model_id.end());
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

    const int scale = (int)scale_arg;
    if ((double)scale != scale_arg || std::find(mi->scales.begin(), mi->scales.end(), scale) == mi->scales.end())
    {
        fprintf(stderr, "unsupported scale %g for model %s (native:", scale_arg, mi->id.c_str());
        for (int s : mi->scales)
            fprintf(stderr, " %dx", s);
        fprintf(stderr, ")\n");
        return EXIT_PARAM;
    }

    if (mi->denoise.find(denoise_level) == mi->denoise.end())
    {
        fprintf(stderr, "model %s does not support denoise level %d\n", mi->id.c_str(), denoise_level);
        return EXIT_PARAM;
    }
    const std::string denoise_token = mi->denoise.at(denoise_level);

    // ---- 模型文件解析（按架构） ----
    path_t model_dir = PATHSTR("models/") + widen(mi->dir);
    path_t parampath;
    path_t binpath;
    int prepadding = 0;

    std::string wdir(mi->dir.begin(), mi->dir.end());
    if (mi->arch == "waifu2x")
    {
        // {dir}/noise{N}_scale2.0x_model.param|bin，token = 噪声编号
        char seg[32];
        snprintf(seg, sizeof(seg), "noise%s_scale2.0x_model", denoise_token.c_str());
        parampath = sanitize_filepath(model_dir + PATHSTR("/") + widen(seg) + PATHSTR(".param"));
        binpath = sanitize_filepath(model_dir + PATHSTR("/") + widen(seg) + PATHSTR(".bin"));
        prepadding = mi->prepad.count(scale) ? mi->prepad.at(scale) : 7;
    }
    else if (mi->arch == "cugan")
    {
        // {dir}/up{scale}-{variant}.param|bin，token = 变体中缀
        char seg[64];
        snprintf(seg, sizeof(seg), "up%dx-%s", scale, denoise_token.c_str());
        parampath = sanitize_filepath(model_dir + PATHSTR("/") + widen(seg) + PATHSTR(".param"));
        binpath = sanitize_filepath(model_dir + PATHSTR("/") + widen(seg) + PATHSTR(".bin"));
        prepadding = mi->prepad.count(scale) ? mi->prepad.at(scale) : 0;
    }
    else // rrdb | compact
    {
        // {dir}/{token}.param|bin，token = 完整基础名（含可选降噪后缀）
        parampath = sanitize_filepath(PATHSTR("models/") + widen(mi->dir + "/" + denoise_token + ".param"));
        binpath = sanitize_filepath(PATHSTR("models/") + widen(mi->dir + "/" + denoise_token + ".bin"));
        prepadding = mi->prepad.count(scale) ? mi->prepad.at(scale) : 0;
    }

    // 模型文件缺失时优雅报错（避免 ncnn 对空 FILE* 崩溃）
    if (!filepath_is_readable(parampath) || !filepath_is_readable(binpath))
    {
        fprintf(stderr, "model files not found: %ls\n", parampath.c_str());
        ncnn::destroy_gpu_instance();
        return EXIT_INFER;
    }

    // ---- 收集输入文件与输出路径（命名规则：A-(模型名)-[nN-]<倍率|尺寸>） ----
    std::wstring wdisplay(mi->display.begin(), mi->display.end());
    std::wstring denoise_seg = denoise_level > 0 ? (L"-n" + std::to_wstring(denoise_level)) : L"";
    wchar_t scale_seg[16];
    swprintf(scale_seg, 16, L"%.1fx", (double)scale);

    bool input_is_dir = path_is_directory(inputpath);

    std::vector<path_t> input_files;
    std::vector<path_t> output_files;
    path_t output_dir;

    auto ext_is_image = [](const path_t& ext) {
        path_t e = ext;
        std::transform(e.begin(), e.end(), e.begin(), ::towlower);
        return e == PATHSTR("jpg") || e == PATHSTR("jpeg") || e == PATHSTR("png") || e == PATHSTR("webp");
    };

    if (input_is_dir)
    {
        std::filesystem::path in(inputpath);
        std::filesystem::path out_dir_path = in.parent_path() / (in.filename().wstring() + L"-(" + wdisplay + L")" + denoise_seg + L"-" + scale_seg);
        output_dir = out_dir_path.wstring();

        std::error_code ec;
        std::filesystem::create_directories(out_dir_path, ec);
        if (ec)
        {
            fprintf(stderr, "cannot create output directory: %ls (%s)\n", output_dir.c_str(), ec.message().c_str());
            return EXIT_IO;
        }

        std::vector<path_t> filenames;
        if (list_directory(inputpath, filenames) != 0)
        {
            fprintf(stderr, "cannot list directory: %ls\n", inputpath.c_str());
            return EXIT_IO;
        }

        for (const path_t& filename : filenames)
        {
            path_t fullpath = inputpath + PATHSTR('/') + filename;
            if (!ext_is_image(get_file_extension(filename)))
                continue;
            input_files.push_back(fullpath);
            path_t stem = get_file_name_without_extension(filename);
            output_files.push_back(output_dir + PATHSTR('/') + stem + PATHSTR('.') + format);
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
        std::filesystem::path in(inputpath);
        std::filesystem::path out_path = in.parent_path() / (in.stem().wstring() + L"-(" + wdisplay + L")" + denoise_seg + L"-" + scale_seg + L"." + format);
        output_files.push_back(out_path.wstring());
    }

    const int total = (int)input_files.size();

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
        fprintf(stderr, "model: %s arch=%s scale=%dx denoise=%d tilesize=%d gpuid=%d\n",
                mi->id.c_str(), mi->arch.c_str(), scale, denoise_level, tilesize, gpuid);
    }

    // ---- 按架构创建引擎并执行 解码 -> 推理 -> 编码 循环 ----
    int rc = EXIT_OK;
    if (mi->arch == "waifu2x")
    {
        Waifu2x* engine = new Waifu2x(gpuid, false, num_threads);
        int lr = engine->load(parampath, binpath);
        if (lr == 0)
        {
            engine->noise = denoise_level; // waifu2x 变体 token 即噪声编号
            engine->scale = scale;
            engine->tilesize = tilesize;
            engine->prepadding = prepadding;
            rc = run_files(engine, input_files, output_files, format, quality, scale, verbose);
        }
        delete engine;
        if (lr != 0)
            rc = EXIT_INFER;
    }
    else if (mi->arch == "cugan")
    {
        RealCUGAN* engine = new RealCUGAN(gpuid, false, num_threads);
        int lr = engine->load(parampath, binpath);
        if (lr == 0)
        {
            engine->noise = denoise_level;
            engine->scale = scale;
            engine->tilesize = tilesize;
            engine->prepadding = prepadding;
            engine->syncgap = 3;
            rc = run_files(engine, input_files, output_files, format, quality, scale, verbose);
        }
        delete engine;
        if (lr != 0)
            rc = EXIT_INFER;
    }
    else // rrdb | compact → RealESRGAN
    {
        RealESRGAN* engine = new RealESRGAN(gpuid, false);
        int lr = engine->load(parampath, binpath);
        if (lr == 0)
        {
            engine->scale = scale;
            engine->tilesize = tilesize;
            engine->prepadding = prepadding;
            rc = run_files(engine, input_files, output_files, format, quality, scale, verbose);
        }
        delete engine;
        if (lr != 0)
            rc = EXIT_INFER;
    }

    ncnn::destroy_gpu_instance();
    return rc;
}
