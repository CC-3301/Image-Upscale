# 【历史存档，勿运行】一次性迁移脚本：目标为 main.cpp 时代的代码（已并入 engine_core.cpp），
# 且当前源码已含这些守卫。保留仅供追溯，勿在现源码上重跑。
# 修复补丁：_wfopen 守卫 + main 降噪支持校验（CRLF/LF 无关，基于精确子串）
import io

def read(p):
    return io.open(p, encoding="utf-8").read()

def write(p, t):
    io.open(p, "w", encoding="utf-8", newline="").write(t)

# 1) 三引擎 _wfopen 失败 → return -1
for p in [
    "engine/src/waifu2x.cpp",
    "engine/src/realcugan.cpp",
    "engine/src/realesrgan.cpp",
]:
    t = read(p)
    n = 0
    for blob in ("parampath", "modelpath"):
        old = (
            'if (!fp)\n        {\n            fwprintf(stderr, L"_wfopen %ls failed\\n", '
            + blob
            + '.c_str());\n        }\n\n        net.load_'
        )
        new = (
            'if (!fp)\n        {\n            fwprintf(stderr, L"_wfopen %ls failed\\n", '
            + blob
            + '.c_str());\n            return -1;\n        }\n\n        net.load_'
        )
        while old in t:
            t = t.replace(old, new, 1)
            n += 1
    write(p, t)
    print(p, "wfopen guards:", n)

# 2) main.cpp 降噪支持校验
p = "engine/src/main.cpp"
t = read(p)
if "does not support denoise level" in t:
    print("main.cpp: denoise check already present")
else:
    old = (
        'fprintf(stderr, "unknown model id: %ls\\n", model_id.c_str());\n'
        "        return EXIT_PARAM;\n    }"
    )
    new = (
        'fprintf(stderr, "unknown model id: %ls\\n", model_id.c_str());\n'
        "        return EXIT_PARAM;\n    }\n\n"
        '    if (mi->denoise.find(denoise_level) == mi->denoise.end())\n'
        "    {\n"
        '        fprintf(stderr, "model %s does not support denoise level %d\\n", mi->id.c_str(), denoise_level);\n'
        "        return EXIT_PARAM;\n    }"
    )
    assert old in t, "main.cpp anchor missing"
    t = t.replace(old, new, 1)
    write(p, t)
    print("main.cpp: denoise check added")
