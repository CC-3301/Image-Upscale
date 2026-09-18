# 【历史存档，勿运行】一次性迁移脚本：绝对路径为当时的开发机布局，现源码已不含被打补丁的代码。
# 保留仅供追溯，请勿运行（会因锚点不存在而静默 no-op）。
# realesrgan.cpp: .spv.hex.h（构建期 SPIRV）→ 运行时编译（幂等版）
import re

P = r"D:/Pi-Project/Image-Upscale/engine/src/realesrgan.cpp"
H = r"D:/Pi-Project/Image-Upscale/engine/src/realesrgan.h"
M = r"D:/Pi-Project/Image-Upscale/engine/src/main.cpp"

with open(P, "r", encoding="utf-8", newline="") as f:
    text = f.read()

# 1) 静态 SPIRV 数组块 → comp 内嵌头（已替换则跳过）
if "realesrgan_preproc.spv.hex.h" in text:
    start = text.index("static const uint32_t realesrgan_preproc_spv_data[] = {")
    end_marker = '#include "realesrgan_postproc_tta_int8s.spv.hex.h"'
    end = text.index(end_marker)
    end = text.index("};", end) + 2
    block_new = (
        '#include "realesrgan_preproc.comp.hex.h"\n'
        '#include "realesrgan_postproc.comp.hex.h"\n'
        '#include "realesrgan_preproc_tta.comp.hex.h"\n'
        '#include "realesrgan_postproc_tta.comp.hex.h"'
    )
    text = text[:start] + block_new + text[end:]
    print("step1: includes replaced")

# 2) tta/非 tta create 分支 → 运行时编译（幂等：已含 compile_spirv_module 则跳过）
if "compile_spirv_module" not in text:
    pat = re.compile(
        r"        if \(tta_mode\)\r?\n        \{\r?\n"
        r"            if \(net\.opt\.use_fp16_storage && net\.opt\.use_int8_storage\)\r?\n"
        r"                realesrgan_preproc->create\(realesrgan_preproc_tta_int8s_spv_data.*?\r?\n"
        r"            else\r?\n"
        r"                realesrgan_preproc->create\(realesrgan_preproc_spv_data, sizeof\(realesrgan_preproc_spv_data\), specializations\);\r?\n\r?\n"
        r"            if \(net\.opt\.use_fp16_storage && net\.opt\.use_int8_storage\)\r?\n"
        r"                realesrgan_postproc->create\(realesrgan_postproc_int8s_spv_data.*?\r?\n"
        r"            else\r?\n"
        r"                realesrgan_postproc->create\(realesrgan_postproc_spv_data, sizeof\(realesrgan_postproc_spv_data\), specializations\);",
        re.DOTALL,
    )
    block_new = """        {
            static std::vector<uint32_t> spirv;
            static ncnn::Mutex lock;
            {
                ncnn::MutexLockGuard guard(lock);
                if (spirv.empty())
                {
                    if (tta_mode)
                        compile_spirv_module(realesrgan_preproc_tta_comp_data, sizeof(realesrgan_preproc_tta_comp_data), net.opt, spirv);
                    else
                        compile_spirv_module(realesrgan_preproc_comp_data, sizeof(realesrgan_preproc_comp_data), net.opt, spirv);
                }
            }
            realesrgan_preproc->create(spirv.data(), spirv.size() * 4, specializations);
        }
        {
            static std::vector<uint32_t> spirv;
            static ncnn::Mutex lock;
            {
                ncnn::MutexLockGuard guard(lock);
                if (spirv.empty())
                {
                    if (tta_mode)
                        compile_spirv_module(realesrgan_postproc_tta_comp_data, sizeof(realesrgan_postproc_tta_comp_data), net.opt, spirv);
                    else
                        compile_spirv_module(realesrgan_postproc_comp_data, sizeof(realesrgan_postproc_comp_data), net.opt, spirv);
                }
            }
            realesrgan_postproc->create(spirv.data(), spirv.size() * 4, specializations);
        }"""
    text, n = pat.subn(block_new, text)
    print(f"step2: create branches replaced x{n}")
else:
    print("step2: already patched")

with open(P, "w", encoding="utf-8", newline="") as f:
    f.write(text)

# 3) realesrgan.h 去重 process_cpu 声明
with open(H, "r", encoding="utf-8", newline="") as f:
    h = f.read()
decl = "    int process_cpu(const ncnn::Mat& inimage, ncnn::Mat& outimage) const;\n"
changed = False
while h.count(decl) > 1:
    idx = h.rindex(decl)
    h = h[:idx] + h[idx + len(decl):]
    changed = True
with open(H, "w", encoding="utf-8", newline="") as f:
    f.write(h)
print("step3: header decl x", h.count(decl), ("(fixed)" if changed else ""))

# 4) main.cpp 游离的 free/return 块删除
with open(M, "r", encoding="utf-8", newline="") as f:
    m = f.read()
stray_pat = re.compile(
    r"    free\(pixeldata\);\r?\n    return rgb;\r?\n\}\r?\n\r?\n    free\(pixeldata\);\r?\n    return rgb;\r?\n\}\r?\n"
)
m, n = stray_pat.subn("    free(pixeldata);\n    return rgb;\n}\n", m)
with open(M, "w", encoding="utf-8", newline="") as f:
    f.write(m)
print("step4: main.cpp stray removed x", n)
