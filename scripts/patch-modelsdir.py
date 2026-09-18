# 【历史存档，勿运行】一次性迁移脚本：目标为 main.cpp 时代的代码（已并入 engine_core.cpp）。
# --models-dir 支持（带断言验证，全部成功才写盘）
p = "engine/src/main.cpp"
t = open(p, encoding="utf-8").read()

ok = True

# 1) 声明
decl_anchor = '    path_t model_id = PATHSTR("waifu2x_upconv_7_art");\n'
if "path_t models_dir = PATHSTR" not in t:
    if decl_anchor not in t:
        print("FAIL: decl anchor missing"); ok = False
    else:
        t = t.replace(decl_anchor, decl_anchor + '    path_t models_dir = PATHSTR("models");\n', 1)

# 2) usage 行
usage_anchor = '    fprintf(stdout, "  -g gpu-id            gpu device (-1=cpu, default: auto)\\n");\n'
if "  --models-dir path " not in t:
    if usage_anchor not in t:
        print("FAIL: usage anchor missing"); ok = False
    else:
        t = t.replace(usage_anchor, usage_anchor + '    fprintf(stdout, "  --models-dir path    models directory (default: models)\\n");\n', 1)

# 3) 参数解析（插在 -g 分支后）
gparse = '''        else if (wcscmp(a, L"-g") == 0 && i + 1 < argc)
        {
            gpuid_arg = _wtoi(argv[++i]);
        }
'''
if "--models-dir" not in t.split("int PATH_MAIN")[1] if "int PATH_MAIN" in t else True:
    pass
parse_new = gparse + '''        else if (wcscmp(a, L"--models-dir") == 0 && i + 1 < argc)
        {
            models_dir = argv[++i];
        }
'''
if "wcscmp(a, L\"--models-dir\")" not in t.split("int PATH_MAIN")[1]:
    if gparse not in t:
        print("FAIL: -g parse anchor missing"); ok = False
    else:
        t = t.replace(gparse, parse_new, 1)

if not ok:
    raise SystemExit("patch failed, nothing written")

open(p, "w", encoding="utf-8", newline="\n").write(t)
print("all patches verified & written")
