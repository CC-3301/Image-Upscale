# 移植适配：realcugan.cpp / realesrgan.cpp → 本引擎约定（RGB 原生、CPU 路径、新版 ncnn 兼容）
import re

BASE = r"D:/Pi-Project/Image-Upscale/engine/src"


def sub(path, pattern, repl, flags=re.MULTILINE):
    with open(path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    new, n = re.subn(pattern, repl, text, flags=flags)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    print(f"{path.rsplit('/', 1)[-1]}: x{n}  <- {pattern[:48]}")


# ---- realcugan.cpp ----
RC = BASE + "/realcugan.cpp"

sub(RC, r"    net\.set_vulkan_device\(vkdev\);",
    """    // 适配：新版 ncnn 指针重载解引用空指针，仅 GPU 设置；CPU 关 int8/sgemm（Deconvolution CPU 崩溃规避）
    if (vkdev)
        net.set_vulkan_device(vkdev);
    else
    {
        net.opt.use_int8_storage = false;
        net.opt.use_sgemm_convolution = false;
    }""")

# #if _WIN32 spec=1 #else spec=0 #endif → 强制 0（RGB）
sub(RC, r"#if _WIN32\r?\n(\s*)specializations\[0\]\.i = 1;\r?\n\s*#else\r?\n\s*specializations\[0\]\.i = 0;\r?\n\s*#endif",
    r"\1specializations[0].i = 0; // RGB 适配")

# 像素序常量统一 RGB（包裹的 #if 两分支变相同，保留无害）
for old, new in [
    ("ncnn::Mat::PIXEL_BGR2RGB", "ncnn::Mat::PIXEL_RGB"),
    ("ncnn::Mat::PIXEL_BGRA2RGBA", "ncnn::Mat::PIXEL_RGBA"),
    ("ncnn::Mat::PIXEL_RGB2BGR", "ncnn::Mat::PIXEL_RGB"),
    ("ncnn::Mat::PIXEL_RGBA2BGRA", "ncnn::Mat::PIXEL_RGBA"),
]:
    sub(RC, re.escape(old), new)

# ---- realesrgan.cpp ----
RG = BASE + "/realesrgan.cpp"

ctor_old = (
    r"    net\.opt\.use_vulkan_compute = true;\r?\n"
    r"    net\.opt\.use_fp16_packed = true;\r?\n"
    r"    net\.opt\.use_fp16_storage = true;\r?\n"
    r"    net\.opt\.use_fp16_arithmetic = false;\r?\n"
    r"    net\.opt\.use_int8_storage = true;\r?\n"
    r"    net\.opt\.use_int8_arithmetic = false;\r?\n"
    r"\r?\n"
    r"    net\.set_vulkan_device\(gpuid\);"
)
ctor_new = (
    "    // 适配：CPU 路径（-g -1）由 process_cpu 支撑；fp16/int8/sgemm 仅 GPU 启用\n"
    "    net.opt.use_vulkan_compute = gpuid != -1;\n"
    "    net.opt.use_fp16_packed = gpuid != -1;\n"
    "    net.opt.use_fp16_storage = gpuid != -1;\n"
    "    net.opt.use_fp16_arithmetic = false;\n"
    "    net.opt.use_int8_storage = false;\n"
    "    net.opt.use_int8_arithmetic = false;\n"
    "    net.opt.use_sgemm_convolution = gpuid != -1;\n"
    "\n"
    "    if (gpuid != -1)\n"
    "        net.set_vulkan_device(gpuid);"
)
sub(RG, ctor_old, ctor_new)

sub(RG, r"#if _WIN32\r?\n(\s*)specializations\[0\]\.i = 1;\r?\n\s*#else\r?\n\s*specializations\[0\]\.i = 0;\r?\n\s*#endif",
    r"\1specializations[0].i = 0; // RGB 适配")

for old, new in [
    ("ncnn::Mat::PIXEL_BGR2RGB", "ncnn::Mat::PIXEL_RGB"),
    ("ncnn::Mat::PIXEL_BGRA2RGBA", "ncnn::Mat::PIXEL_RGBA"),
    ("ncnn::Mat::PIXEL_RGB2BGR", "ncnn::Mat::PIXEL_RGB"),
    ("ncnn::Mat::PIXEL_RGBA2BGRA", "ncnn::Mat::PIXEL_RGBA"),
]:
    sub(RG, re.escape(old), new)

# 管线创建仅 GPU（CPU 下 net.vulkan_device() 为空）
sub(RG, r"    // initialize preprocess and postprocess pipeline\r?\n    \{",
    "    // initialize preprocess and postprocess pipeline (GPU only)\r\n    if (net.vulkan_device())\r\n    {")

# ---- realesrgan.h：声明 process_cpu ----
RH = BASE + "/realesrgan.h"
sub(RH, r"    int process\(const ncnn::Mat& inimage, ncnn::Mat& outimage\) const;",
    """    int process(const ncnn::Mat& inimage, ncnn::Mat& outimage) const;

    int process_cpu(const ncnn::Mat& inimage, ncnn::Mat& outimage) const;""")

print("adaptation done")
