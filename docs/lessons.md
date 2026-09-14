# 坑与教训（Lessons Learned）

> 项目迭代中真实踩过的坑，每条按 **现象 → 根源 → 教训 → 守卫** 记录。改动对应区域前先扫对应小节；新增条目沿用四段格式，过时的条目直接删除。工单出处标注在标题里，细节见 `.scratch/image-upscale/issues/`。

## 1. 引擎（C++ / ncnn）

### 1.1 elempack 是编码器的通道数依据（工单 10）

- **现象**：目标尺寸与直通缩放路径输出黑白图、内容纵向压扁 3 倍；倍率模式完全正常。
- **根源**：`resize_rgb` 用三参 `Mat::create(w, h, channels)`，该重载置 `elempack=1`；编码器以 `outimage.elempack` 为通道数写出 → RGB 交错流被当单通道截断。"整 2 倍捷径"路径不做 resize 所以幸免。
- **教训**：创建或包装 ncnn::Mat 时显式写四参 `create(w, h, elemsize, elempack)`；看到"彩色变灰 + 纵向压扁"组合，先查 elempack 元数据。
- **守卫**：`tests/test_size_modes.py` 断言产物 `mode == "RGB"`（倍率 / resize / 捷径 / 直通 / JPG 五条路径）。

### 1.2 非拥有 Mat + 块作用域缓冲 = 按尺寸触发的 use-after-free（工单 15）

- **现象**：RGBA 大图（合并缓冲 ≥0.5MB）输出 PNG/WebP 必崩 0xC0000005；同代码小图"正常"；JPG（走另一分支）正常。
- **根源**：`merged` vector 是 `if` 块局部变量，`outimage` 用其 `data()` 构造**非拥有视图**；块结束 vector 析构，编码阶段读已释放内存。小分配 free 后堆页未去提交 → 侥幸不崩；大分配（VirtualAlloc）free 即去提交 → 必崩。
- **教训**："小图没事、大图崩"是内存生存期 bug 的签名症状，别当偶发问题；ncnn::Mat 包装外部指针不持有引用，缓冲生存期必须覆盖到写盘完成。
- **守卫**：`tests/test_alpha.py` 大图 RGBA（512×512）× 三种输出格式。

### 1.3 跨进程输出的编码必须钉死为 UTF-8（工单 17）

- **现象**：中文/日文文件名在 GUI 日志乱码。
- **根源**：`fprintf("%ls")` 在输出重定向下经 C locale（中文 Windows = GBK）转多字节，GUI 按 UTF-8 解码必乱码；GBK 无法表示假名（输出 `?`）。同类：narrow `fopen` 遇非 ASCII 路径同炸（`parse_manifest` 已改 `_wfopen`）。
- **教训**：引擎对管道的所有含路径输出统一走 `utf8_from_wide()`（WideCharToMultiByte CP_UTF8），控制台直跑另加 `SetConsoleOutputCP(CP_UTF8)`；新增输出点禁止直接 `%ls`。
- **守卫**：`tests/test_output_encoding.py`（中文 + 日文文件名）。

### 1.4 资源定位按 exe 自身位置，不信任 CWD（工单 16 缺陷）

- **现象**：引擎挪进 `engine/` 子目录后，GUI 启动即报 `cannot read models/manifest.conf`。
- **根源**：manifest 路径按 CWD 相对硬编码，而 GUI 以引擎所在目录为工作目录启动；且 `--models-dir` 只管模型文件、管不到清单（同一概念两处真相）。
- **教训**：资源定位顺序 = 显式参数 > exe 所在目录 > exe 上级 > CWD；一个概念（models 目录）只允许一个解析来源。
- **守卫**：`tests/test_models.py`（dist 布局模拟 + 显式 `--models-dir` 优先）。

### 1.5 GUI↔引擎行契约的每一侧都要有守卫

- **现象**：GUI 在 stdout 找 `" done"` 后缀显示 ✔ 成功行，引擎却把成功行打在 verbose stderr → ✔ 永不触发，无人发现。
- **教训**：行协议（`progress d/t` / `<in> -> <out> done` / `done` / 退出码 0/1/2/3）是两侧共同契约；改任何一侧先核对另一侧，输出流（stdout 还是 stderr）写死并各留测试。
- **守卫**：`tests/test_exit_codes.py`、GUI 手动验收清单（工单 08）。

## 2. GUI（WPF）

### 2.1 经典主题渲染下控件文字顶对齐（工单 12）

- **根源**：系统以经典主题渲染时 ComboBox 等默认模板文字垂直顶对齐。
- **教训**：文本承载控件显式 `VerticalContentAlignment="Center"`（用 Window.Resources 隐式样式一次覆盖），不依赖主题默认值。

### 2.2 TextBox 吞拖拽冒泡事件（工单 11）

- **现象**：拖文件到输入框无效，拖窗口其他区域正常。
- **根源**：TextBox 内建处理拖拽事件且不冒泡，窗口级 `Drop` 收不到。
- **教训**：控件级接受拖放用隧道事件 `PreviewDragOver` / `PreviewDrop`。

### 2.3 布局自适应与日志面板（工单 18/19）

- 横向 StackPanel 在窄窗口下溢出即被裁剪且不可达 → 功能行用 `WrapPanel` + Window `MinWidth`/`MinHeight`。
- 日志区用 `*` 行 + `GridSplitter`（`ResizeBehavior="PreviousAndNext"`）拖拽调高，`MinHeight` 设下限；ScrollViewer 与 GridSplitter 行为冲突，本布局靠 Min 尺寸兜底、未加滚动。

### 2.4 降噪能力判据与持久化边界（工单 23/24/14）

- "支持降噪" = 清单存在 **none 以外**档位；仅 none 的模型灰置控件并固定"无"，否则引擎参数错误。
- 降噪档位是**临时选择**（grilling 定案）：不持久化，启动与切换模型一律回默认档（支持→自动，不支持→无）。持久化只记模型、尺寸模式+各模式数值、格式、质量（`setting.ini`，exe 同目录，waifu2x-caffe 同构）。

## 3. 流程与分诊

### 3.1 修复进了工作区 ≠ 修复到了用户手里

- **现象**：灰度 bug 的修复在工作区躺了半天，bld 与 dist 的 exe 都是修复前构建，用户测到的永远是坏包。
- **教训**：源码修复后立即重建并刷新分发物；"我明明修了用户还能复现"第一步查二进制新旧（对比源码与 exe 的 mtime）。

### 3.2 测试夹具必须覆盖被守护的维度

- **现象**：夹具全为灰度图且只断言尺寸，颜色通道回归全绿通过。
- **教训**：夹具要有彩色 / RGBA / 非整倍尺寸变体；断言 `mode` 与内容，而不是只断言 `size`。

### 3.3 冒烟必须复刻真实启动环境

- **现象**：打包冒烟从包根跑引擎（CWD 恰好命中 models/），GUI 实际以 engine/ 子目录为 CWD → manifest 缺陷漏网，被人工测试抓到。
- **教训**：冒烟的 CWD、工作目录、启动参数必须与 GUI 的真实启动方式一致，而不是"能跑通就行"。

### 3.4 报告的现象 ≠ 根因，先复现再归因

- **现象**：用户报"PNG + 质量 <100 报错"，截图日志里的真相是退出码 -1073741819（0xC0000005）——alpha 大图崩溃，与格式质量无关。
- **教训**：分诊时用引擎 CLI（唯一测试缝）直接复现，请报告者提供完整日志/截图；表面归因会导向错误的修复位置。

### 3.5 测试缝上 TDD 红→绿

- alpha 崩溃、UTF-8、资源定位三个缺陷都先写红测试（证明测试抓得住）再修复（证明修复有效）。引擎 CLI 进程边界是本项目的唯一测试缝（spec 定案），新缺陷先落成该缝上的回归测试。

### 3.6 零删除打包

- `package.ps1` 输出到版本化目录（`dist/vX.Y.Z/`），从不对旧产物做删除；zip 同名冲突时报错提示换版本号。修复缺陷后的重新发布 = 新版本目录，旧包由人工处置。

## 4. 本机工具链备忘（Windows）

以下为该开发机的环境事实，任何配置文件里都查不到：

- **cmake 不在 PATH**：用 MSVC 自带 `D:\Software\MSVC\...\CMake\bin\cmake.exe`，构建前需 `vcvars64.bat`——已封装在 `scripts\engine-build.bat`，不要手写编译命令。
- **Git Bash 调 cmd**：`cmd /c` 的 `/c` 会被路径转换吃掉 → 用 `cmd //c "D:\\完整\\路径.bat"`。
- **PowerShell 5.1 + 含中文的 .ps1**：无 BOM 的 UTF-8 被按 ANSI 解析、中文注释炸语法 → .ps1 存成 UTF-8 with BOM。
- **dotnet SDK** 在 `D:\Software\DotNet\dotnet.exe`（Program Files 里那个只有运行时，build/publish 会报"下载 SDK"）。
- **测试跑法**：`set IU_ENGINE=<bld>\image-upscale.exe` 后 `python -m pytest tests -q`（conftest 默认的 `build/Release` 路径在本布局不存在）。
- **测试对 CWD 的要求**：引擎现在按自身位置找 models，测试从仓库根跑即可；测试统一 `-g -1`（CPU 后端）保证确定性，GPU 只留 smoke。
