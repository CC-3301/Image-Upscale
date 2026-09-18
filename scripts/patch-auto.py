# 【历史存档，勿运行】工单 06 的一次性迁移脚本：目标是 main.cpp 时代的代码（已并入 engine_core.cpp）。
# 现在跑只会静默 no-op（replace 锚点已不存在）却仍打印 "patches applied"，保留仅供追溯。
# 工单 06：AUTO 降噪（估计器 + CLI/命名集成）
import re

P = "engine/src/main.cpp"
t = open(P, encoding="utf-8").read()

# 1) 估计器（插在 widen 助手之后）
estimator = '''
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
'''
anchor = "// ASCII → 宽字符（清单 id/变体 token 均为 ASCII，足够）"
assert anchor in t, "widen anchor missing"
t = t.replace(anchor, estimator + "\n" + anchor, 1)

# 2) CLI：--denoise auto
t = t.replace('''            std::wstring d = argv[++i];
            if (d == L"none") denoise_level = 0;
            else if (d == L"low") denoise_level = 1;
            else if (d == L"mid") denoise_level = 2;
            else if (d == L"high") denoise_level = 3;
            else
            {
                fprintf(stderr, "invalid --denoise level (none/low/mid/high)\\n");
                return EXIT_PARAM;
            }''',
'''            std::wstring d = argv[++i];
            if (d == L"none") denoise_level = 0;
            else if (d == L"low") denoise_level = 1;
            else if (d == L"mid") denoise_level = 2;
            else if (d == L"high") denoise_level = 3;
            else if (d == L"auto") denoise_auto = true;
            else
            {
                fprintf(stderr, "invalid --denoise level (auto/none/low/mid/high)\\n");
                return EXIT_PARAM;
            }''')
t = t.replace("    int denoise_level = 0; // 0=无 1=低 2=中 3=高（AUTO 在工单 06）",
              "    int denoise_level = 0; // 0=无 1=低 2=中 3=高\n    bool denoise_auto = false; // AUTO：按文件伪影估计自动选档（工单 06）")

# 3) AUTO 前置校验：模型须支持至少一个非 none 档位（在模型查找后）
anchor2 = '''    if (mi->denoise.find(denoise_level) == mi->denoise.end())
    {
        fprintf(stderr, "model %s does not support denoise level %d\\n", mi->id.c_str(), denoise_level);
        return EXIT_PARAM;
    }'''
add2 = '''    if (denoise_auto)
    {
        bool any_level = mi->denoise.count(1) || mi->denoise.count(2) || mi->denoise.count(3);
        if (!any_level)
        {
            fprintf(stderr, "model %s does not support denoise (cannot use AUTO)\\n", mi->id.c_str());
            return EXIT_PARAM;
        }
        denoise_level = 0; // 具体档位按文件估计（见 run_files）
    }
''' + anchor2
if "cannot use AUTO" not in t:
    assert anchor2 in t, "denoise check anchor missing"
    t = t.replace(anchor2, add2, 1)

# 4) run_files：denoise_auto 参数 + 每文件解析
t = t.replace("static int run_files(Engine* engine, const ModelInfo& mi, int denoise_level,",
              "static int run_files(Engine* engine, const ModelInfo& mi, int denoise_level, bool denoise_auto,")
t = t.replace("""        bool use_engine = true;
        int file_scale = run_scale;""",
"""        // AUTO：按当前文件伪影估计规范档位（单文件命名与模型变体都使用解析结果）
        int file_denoise = denoise_level;
        if (denoise_auto)
        {
            file_denoise = estimate_denoise_level(pixeldata, w, h);
            if (verbose)
                fprintf(stderr, "denoise: auto resolved level=%d\\n", file_denoise);
        }

        bool use_engine = true;
        int file_scale = run_scale;""")
t = t.replace("""        path_t outpath;
        if (single_file)
        {
            std::filesystem::path in(inpath);
            outpath = single_file_outpath(in, wdisplay, denoise_seg, scale_seg, wext, !use_engine);
        }""",
"""        std::wstring file_denoise_seg = denoise_auto && file_denoise > 0
            ? (L"-n" + std::to_wstring(file_denoise))
            : denoise_seg;
        path_t outpath;
        if (single_file)
        {
            std::filesystem::path in(inpath);
            outpath = single_file_outpath(in, wdisplay, file_denoise_seg, scale_seg, wext, !use_engine);
        }""")
t = t.replace("""            if (file_scale != loaded_scale)
            {
                resolve_model_files(mi, file_scale, denoise_level, cur_param, cur_bin, cur_prepad);""",
"""            if (file_scale != loaded_scale || (denoise_auto && file_denoise != denoise_level))
            {
                resolve_model_files(mi, file_scale, file_denoise, cur_param, cur_bin, cur_prepad);""")
t = t.replace("            engine->configure(file_scale, denoise_level, tilesize, cur_prepad);",
              "            engine->configure(file_scale, file_denoise, tilesize, cur_prepad);")
t = t.replace("""                     const std::wstring& scale_seg, int tilesize, bool verbose)""",
"""                     const std::wstring& scale_seg, int tilesize, bool denoise_auto, bool verbose)""")
t = t.replace("scale_seg, tilesize, verbose);", "scale_seg, tilesize, denoise_auto, verbose);")

open(P, "w", encoding="utf-8", newline="\n").write(t)
print("ticket 06 patches applied")
