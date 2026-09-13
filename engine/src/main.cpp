// image-upscale 引擎 CLI（工单 01）
// 命令面、命名规则、格式/质量控制为本项目原创；
// tiled 推理内核适配自 nihui/waifu2x-ncnn-vulkan（MIT，见 NOTICE.md）
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
#include <vector>
#include <algorithm>
#include <clocale>
#include <filesystem>

// 图像编解码：stb（jpg/png）+ libwebp（webp）
#include "stb_image.h"
#include "stb_image_write.h"
#include "webp_image.h"

// ncnn
#include "cpu.h"
#include "gpu.h"
#include "platform.h"

#include "waifu2x.h"

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
    fprintf(stdout, "  -m model-name        model directory name under models/ (default: upconv_7_anime_style_art_rgb)\n");
    fprintf(stdout, "  -s scale             upscale ratio, must be a native scale of the model (default: 2.0)\n");
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

int PATH_MAIN(int argc, wchar_t** argv)
{
    path_t inputpath;
    path_t model = PATHSTR("upconv_7_anime_style_art_rgb");
    double scale_arg = 2.0;
    path_t format = PATHSTR("jpg");
    int quality = 90;
    int tilesize_arg = 0;
    int gpuid_arg = -1000; // -1000 = auto
    int verbose = 0;

    setlocale(LC_ALL, "");

    // 简单参数解析（与 nihui getopt 等价的宽字符手写版）
    for (int i = 1; i < argc; i++)
    {
        wchar_t* a = argv[i];
        if (wcscmp(a, L"-i") == 0 && i + 1 < argc)
        {
            inputpath = argv[++i];
        }
        else if (wcscmp(a, L"-m") == 0 && i + 1 < argc)
        {
            model = argv[++i];
        }
        else if (wcscmp(a, L"-s") == 0 && i + 1 < argc)
        {
            scale_arg = wcstod(argv[++i], NULL);
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

    // 工单 01：仅接受模型原生倍率 2.0（后续工单随模型清单扩展）
    if (scale_arg != 2.0)
    {
        fprintf(stderr, "unsupported scale for this model (native: 2.0x)\n");
        return EXIT_PARAM;
    }

    if (tilesize_arg != 0 && tilesize_arg < 32)
    {
        fprintf(stderr, "invalid tilesize argument (>=32 or 0=auto)\n");
        return EXIT_PARAM;
    }

    // ---- 模型类型与文件（01：upconv_7 系 / cunet；noise 固定 0 = 无降噪，工单 03 引入 --denoise） ----
    int prepadding = 0;
    bool is_upconv = model.find(PATHSTR("upconv")) != path_t::npos;
    bool is_cunet = model.find(PATHSTR("cunet")) != path_t::npos;
    if (is_upconv)
    {
        prepadding = 7;
    }
    else if (is_cunet)
    {
        prepadding = 18;
    }
    else
    {
        fprintf(stderr, "unknown model type: %ls\n", model.c_str());
        return EXIT_PARAM;
    }

    // 模型目录解析：相对 models/，也接受直接相对路径
    path_t model_dir = model;
    if (model.find(PATHSTR('/')) == path_t::npos && model.find(PATHSTR('\\')) == path_t::npos)
    {
        model_dir = PATHSTR("models/") + model;
    }

    path_t parampath = sanitize_filepath(model_dir + PATHSTR("/noise0_scale2.0x_model.param"));
    path_t binpath = sanitize_filepath(model_dir + PATHSTR("/noise0_scale2.0x_model.bin"));

    // ---- 收集输入文件与输出路径（命名规则） ----
    bool input_is_dir = path_is_directory(inputpath);

    std::vector<path_t> input_files;
    std::vector<path_t> output_files;
    path_t output_dir;

    // 大小写不敏感的扩展名匹配（规格：jpg/jpeg/png/webp）
    auto ext_is_image = [](const path_t& ext) {
        path_t e = ext;
        std::transform(e.begin(), e.end(), e.begin(), ::towlower);
        return e == PATHSTR("jpg") || e == PATHSTR("jpeg") || e == PATHSTR("png") || e == PATHSTR("webp");
    };

    if (input_is_dir)
    {
        // 命名规则：A -> 同级 "A-(模型名)-2.0x"
        std::filesystem::path in(inputpath);
        std::filesystem::path out_dir_path = in.parent_path() / (in.filename().wstring() + L"-(" + model + L")-2.0x");
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
        // 命名规则：单文件 A.png -> 同目录 A-(模型名)-2.0x.jpg
        std::filesystem::path in(inputpath);
        std::filesystem::path out_path = in.parent_path() / (in.filename().wstring() + L"-(" + model + L")-2.0x." + format);
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

    // tile 自动策略（沿用 nihui 按显存堆预算分档）
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
            if (is_cunet)
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
            else
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

    Waifu2x* waifu2x = new Waifu2x(gpuid, false, num_threads);

    int load_result = waifu2x->load(parampath, binpath);
    if (load_result != 0)
    {
        fprintf(stderr, "model load failed (%ls / %ls)\n", parampath.c_str(), binpath.c_str());
        delete waifu2x;
        ncnn::destroy_gpu_instance();
        return EXIT_INFER;
    }

    waifu2x->noise = 0;
    waifu2x->scale = 2;
    waifu2x->tilesize = tilesize;
    waifu2x->prepadding = prepadding;

    if (verbose)
    {
        fprintf(stderr, "model: %ls (prepadding=%d tilesize=%d gpuid=%d)\n", model.c_str(), prepadding, tilesize, gpuid);
    }

    // ---- 主循环：逐文件 解码 -> 推理 -> 编码（顺序流水，进度行输出到 stdout） ----
    int done = 0;
    int infer_failures = 0;
    int io_failures = 0;

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
                fprintf(stderr, "cannot open input: %ls\n", inpath.c_str());
                io_failures++;
                done++;
                printf("progress %d/%d\n", done, total);
                fflush(stdout);
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
                fprintf(stderr, "cannot read input: %ls\n", inpath.c_str());
                free(filedata);
                io_failures++;
                done++;
                printf("progress %d/%d\n", done, total);
                fflush(stdout);
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
            fprintf(stderr, "decode image failed: %ls\n", inpath.c_str());
            io_failures++;
            done++;
            printf("progress %d/%d\n", done, total);
            fflush(stdout);
            continue;
        }

        // 01 阶段：alpha 拍平白底，全链路 3 通道（工单 04 实现 alpha 保留）
        if (c == 4)
        {
            unsigned char* rgb = flatten_alpha_to_white(pixeldata, w, h);
            if (!rgb)
            {
                fprintf(stderr, "out of memory: %ls\n", inpath.c_str());
                io_failures++;
                done++;
                printf("progress %d/%d\n", done, total);
                fflush(stdout);
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
        ncnn::Mat outimage(w * 2, h * 2, (size_t)3, 3);
        int pre = waifu2x->process(inimage, outimage);
        free(pixeldata);

        if (pre != 0)
        {
            fprintf(stderr, "inference failed: %ls\n", inpath.c_str());
            infer_failures++;
            done++;
            printf("progress %d/%d\n", done, total);
            fflush(stdout);
            continue;
        }

        // 编码（按输出格式；质量参数作用于 jpg/webp）
        bool save_ok = false;
        path_t ext = format;
        if (ext == PATHSTR("jpg"))
        {
            MemBuffer buf;
            if (stbi_write_jpg_to_func(stb_write_callback, &buf, outimage.w, outimage.h, 3, outimage.data, quality))
            {
                save_ok = write_file_wide(outpath, buf.data.data(), buf.data.size());
            }
        }
        else if (ext == PATHSTR("png"))
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
            fprintf(stderr, "encode image failed: %ls\n", outpath.c_str());
            io_failures++;
        }
        else if (verbose)
        {
            fprintf(stderr, "%ls -> %ls done\n", inpath.c_str(), outpath.c_str());
        }

        done++;
        printf("progress %d/%d\n", done, total);
        fflush(stdout);
    }

    printf("done\n");
    fflush(stdout);

    delete waifu2x;
    ncnn::destroy_gpu_instance();

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
