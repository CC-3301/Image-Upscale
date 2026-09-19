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

### 1.3 跨进程输出的编码必须钉死为 UTF-8（工单 17；日志出口统一见工单 48）

- **现象**：中文/日文文件名在 GUI 日志乱码。
- **根源**：`fprintf("%ls")` 在输出重定向下经 C locale（中文 Windows = GBK）转多字节，GUI 按 UTF-8 解码必乱码；GBK 无法表示假名（输出 `?`）。同类：narrow `fopen` 遇非 ASCII 路径同炸（`parse_manifest` 已改 `_wfopen`）。
- **教训**：引擎对管道的所有含路径输出统一走 `iu_to_utf8()`（`engine/src/iu_log.h`，WideCharToMultiByte CP_UTF8）；**模型实现侧**（waifu2x / realcugan / realesrgan）的提示再经 `iu_log_path_error()` 走同一个头的 sink，由 `iu_run` 登记宿主回调 —— 除 `main.cpp` 的控制台壳外禁止直写 stderr。控制台直跑另加 `SetConsoleOutputCP(CP_UTF8)`；新增输出点禁止直接 `%ls`。
- **守卫**：`tests/test_output_encoding.py`（中文 + 日文文件名）；`tests/test_models.py::test_model_open_failure_reaches_log_sink`（三个模型 TU 各一处「权重打不开」，必须经 sink 到达宿主 stderr；去掉 `iu_run` 里的 sink 登记即三档全红）。

### 1.4 资源定位按 exe 自身位置，不信任 CWD（工单 16 缺陷）

- **现象**：引擎挪进 `engine/` 子目录后，GUI 启动即报 `cannot read models/manifest.conf`。
- **根源**：manifest 路径按 CWD 相对硬编码，而 GUI 以引擎所在目录为工作目录启动；且 `--models-dir` 只管模型文件、管不到清单（同一概念两处真相）。
- **教训**：资源定位顺序 = 显式参数 > exe 所在目录 > exe 上级 > CWD；一个概念（models 目录）只允许一个解析来源。
- **守卫**：`tests/test_models.py`（dist 布局模拟 + 显式 `--models-dir` 优先）。

### 1.5 GUI↔引擎行契约的每一侧都要有守卫

- **现象**：GUI 在 stdout 找 `" done"` 后缀显示 ✔ 成功行，引擎却把成功行打在 verbose stderr → ✔ 永不触发，无人发现。
- **教训**：行协议（`progress d/t` / `<in> -> <out> done` / `done` / 退出码 0/1/2/3）是两侧共同契约；改任何一侧先核对另一侧，输出流（stdout 还是 stderr）写死并各留测试。
- **守卫**：`tests/test_exit_codes.py`、GUI 手动验收清单（工单 08）。

### 1.6 上游 ncnn 移植可能缺官方的输入/输出变换（工单 38/40）

- **现象**：`realcugan-pro` 在部分真实漫画内容上整幅崩成彩色噪声（chroma 异常像素 ~86%），同一模型换一张内容就完全正常；`realcugan-se` 从不崩。切任何 syncgap 档位、换 tile 大小、CPU/GPU 都一样。
- **根源**：官方 Real-CUGAN 对 **pro 系权重**（`weights_pro/*.pth`）在 pytorch 侧有仿射归一化：输入 `x/255*0.7+0.15`、输出 `(y-0.15)*255/0.7`（`upcunet_v3.py` 的 `np2tensor` / `forward`）。nihui 的 ncnn 移植**没有这对变换**（上游 issue #52，至今 OPEN），本项目照搬该移植后 pro 权重一直跑在训练分布之外。普通内容看不出是因为网络近似仿射等变、两次变换近似相消（同一张图两种做法 RMSE≈7/255），高对比网点内容才把激活推出量程。
- **教训**：照抄上游移植只能保证行为一致，**不保证与官方实现一致**；“换个内容就崩、换参数无效”是分布外问题的签名，先去官方原实现（而非另一个移植）核对 pre/post 处理。权重族名（pro / nose / se）与是否需要该变换直接相关，看名称就能缩小范围。
- **守卫**：`tests/test_cugan_pro_norm.py`（合成高对比网点图，断言 chroma 异常像素占比；修复前 0.667，修复后 0.029）。

### 1.7 上游默认参数值不等于对本项目可用值（工单 38）

- **现象**：Real-CUGAN 出图大面积彩噪（pro）/ 线条黄边（se），换分辨率、换内容都时好时坏。
- **根源**：Real-CUGAN 的 SE 描述子是**全图**平均量，分块推理必须同步；引擎把上游 CLI 的默认档位 3（very rough）写死。该档位用固定的 32px 小图块平均描述子后全局复用，会把权重推出分布（pro 整幅崩、se 留黄边），且只覆盖 3 的倍数个图块、尾部图块无人写入。
- **教训**：上游 CLI 的默认值是其命令行工具语境下的取舍；我们把同一份内核当库使用时，默认值必须重新评估（本项定稿为档位 2：与 tile 同尺寸、耗时 +5%）。固定小图块的“粗略近似”在大图上会退化成错值，不是略粗。
- **守卫**：`tests/test_cugan_sync.py`（同步路径与单图块直通不得灾难级偏离）。

### 1.8 原地覆盖源文件：安全的前提与不可撤销的代价（工单 58）

- **现象**：关闭「文件添加扩展名」（引擎 `--no-rename`）且输出格式与输入相同时（`A.png` + `-f png`），产物路径就是输入路径。工单 50 曾加「拒绝写盘」守卫；工单 58 按维护者定案撤销守卫，改为**原地覆盖**（源图被替换、不可恢复）。
- **前提（改这一带前必须逐行复核）**：输入在解码阶段一次性读入内存并立即 `fclose`（`engine_core.cpp` 的 `run_files` 循环开头），写盘发生在推理 / 直通缩放 / alpha 合成之后 → 中途没有第二次读输入路径的通路，原地写不会读到半写状态。唯一另一处文件读取是 `probe_denoise_level`，只在目录分支调用，与单文件场景不相交。
- **代价**：覆盖是**非原子**的（直接截断写目标），写盘途中断电/崩溃会留下截断的源图；且无备份、无二次确认（维护者定案接受）。要原子性得走「写临时文件 + rename」，本仓库明确不做。
- **教训**：给「同路径覆盖」开绿灯前，先把「输入何时读完、写盘何时发生、中途是否重读」三件事在代码里逐行确认，并把结论写进调用点注释——这是该不变量在仓库里的唯一落点。
- **守卫**：`tests/test_naming.py` 的原地覆盖用例（退出码 0 + 尺寸/格式 + 与参考产物的 PSNR 内容判据）。

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

### 2.4 降噪能力判据与持久化边界（工单 23/24/14/49）

- "支持降噪" = 清单存在 **none 以外**档位；仅 none 的模型灰置控件并固定"无"，否则引擎参数错误。
- 降噪档位**跨模型切换与重启记忆**（工单 49 修定，取代原 grilling 的"临时选择、不持久化"定案）：档位齐备（无/低/中/高）的模型共用一份全局记忆、默认"自动"；档位不齐的模型各自独立记忆、默认**最高可用档**（`realcugan-pro` = 无/高 → "高"）；记忆值在当前模型不可用 → 回退默认档；不支持降噪的模型固定"无"并灰置。
- **程序化设置 `SelectedIndex` 会触发同一个 `SelectionChanged`**：`OnModelChanged` 里恢复/回退默认档时必须用抑制标志（`_suppressDenoiseWrite`）包住，否则回退值会经事件写回记忆，把用户存的档位抹掉（同工单 51 的 `_suppressAddSuffixWrite` 模式）。
- **持久化清单**（`setting.ini`，exe 同目录，waifu2x-caffe 同构）：模型、尺寸模式 + 各模式数值、输出格式 + 质量、降采样方式（`LastDownFilter`，工单 42）、文件添加扩展名（`LastAddSuffix`，工单 51）、降噪档位（`LastDenoise` / `LastDenoise_<modelId>`，工单 49）、窗口几何（`LastWindowLeft/Top/Width/Height/Maximized`，工单 25）；逐项校验，非法值静默回退默认。

### 2.5 "与界面统一"的字体需求 = 继承全局默认，不是换字体名（工单 35）

- **现象**：日志字体两轮返工：Consolas → 维护者指名 SimHei 仍不满意。
- **根源**：全局 XAML 从未设过 FontFamily，"其余中文"其实是 WPF 默认回退（微软雅黑）；给日志单独指定任何字体（等宽或黑体）都必然与其余文字不同源，"不统一"观感无解。
- **教训**："和界面统一"类需求，正确动作是删掉控件的显式 FontFamily 让其继承全局默认，而不是再指定一个新字体名；动手前先查全局设没设。
- **守卫**：视觉项无自动化测试；LogBox 现状只留 `FontSize="16"`（v0.2.4 由 14 上调），无 FontFamily。

### 2.6 固定文案类需求不要新增源码字面量断言（工单 52）

- **现象**：启动行文案被来回改过两次，实施者为防回归新增 `tests/test_startup_log_wording.py`，直接读 `gui/MainWindow.xaml.cs` 的源码文本做子串断言 → 两轴评审同轮判越界，最终删除。
- **根源**：spec 的测试缝只有两条（引擎 CLI 进程边界、`iu_engine.dll` 导出面），断言对象限定为文件系统产物 / 退出码 / stderr 文案；源码文本断言不是行为断言——提炼方法、改注释都会误红，且与「GUI 无自动化测试（手动验收）」定案冲突。
- **教训**：文案/视觉类回归靠三件套守：票面留痕（含「定案变更记录」这类作废历史的口径）+ 代码注释写明「勿再改回」+ 人工验收清单。要上自动化守卫，先改 spec 的 Testing Decisions 再写测试。
- **守卫**：`spec.md`「Testing Decisions」；工单 52 的 r1 裁决记录。

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

### 3.7 优雅关闭冒烟不能 taskkill /F（工单 25 验证）

- **现象**：重打包后冒烟 setting.ini 不落盘；另 dist/vX.Y.Z 目录 mv 报 Permission denied。
- **根源**：`taskkill /F` 是 TerminateProcess，WPF 收不到 Closing，"关闭时写 setting.ini"根本没机会执行；不带 /F 的 taskkill 发 WM_CLOSE 才是优雅关闭。进程句柄未释放期间目录被锁。
- **教训**：验证"关闭时持久化/清理"类行为必须优雅关闭（taskkill 不加 /F），强杀只适合清僵尸；重打包/挪目录前确认进程已退出。
- **守卫**：冒烟序列 = start → sleep → taskkill（无 /F）→ sleep → 查 setting.ini。

### 3.8 "放大 LOGO"先对齐语义参照物（工单 32）

- **现象**：LOGO 三轮返工：加宽 → 极限宽 → 压缩字体都不满意，维护者始终说"不够大"。
- **根源**："放大"的真实语义是"英文字形占整个 LOGO 的比例"而非字号；文字版字形高宽比被字体锁死（宽约束下 Segoe 字高只占画布 ~45%），怎么调字号都填不满。
- **教训**：视觉需求的量化词（大/小、比例）先问清参照物（字号？画布占比？）再动手；要"字形铺满"只能几何拼装（mask + 竖条/半圆环自绘），文字渲染无解。工具坑：该版 PIL `rounded_rectangle` 不支持逐角 radius（传 tuple 直接 TypeError），几何形用 mask 拼装；RGBA 上量"白色像素 bbox"必须带 alpha 判据，否则抗锯齿/缩放振铃沿高亮边缘产生假白点。
- **守卫**：定稿参数存 `make_logo_iu_geo.py`（pad160 留白档）；逐像素四边等宽已实测（各 160px）。

### 3.9 发版版本号两处真相：package.ps1 -Version 与 GUI csproj <Version>（v0.2.4 覆盖发布）

- **现象**：v0.2.4 重新打包后，GUI 标题栏仍显示 v0.2.3。
- **根源**：版本号有两处真相——package.ps1 的 `-Version` 只决定 dist 目录/zip 名，而 GUI 标题栏（工单 31）运行时读 csproj `<Version>`；打包脚本不同步也不校验，发版漏改 csproj 无人拦截。
- **教训**：发版动作清单必须包含"改 csproj `<Version>`"；同一版本号概念要么只留一处真相，要么在打包入口强校验。
- **守卫**：**已实施** —— package.ps1 的 `-Version` 改为**必填**，并在打包前强校验 csproj `<Version>`；漏传或与 csproj 不一致即报错（README 构建段示例同步为 `-Version vX.Y.Z`，原写死 `v0.2.2`）。

### 3.10 判“是不是我们的问题”要拿官方原实现做参照物，不能拿另一个移植（工单 38/40）

- **现象**：工单 38 曾把 `realcugan-pro` 的崩坏归因为“上游模型/实现固有失稳”，并计划换模型规避；工单 40 才查清是引擎缺了官方预处理变换。
- **根源**：当时只对照了上游 ncnn 移植的行为，发现“我们和官方预编译 exe 表现一致”就收工了。但上游 ncnn 移植自己也漏了官方的变换，所以“两边一致”只证明忠实搬运，不证明正确。
- **教训**：排除自身责任时，参照物要选**规格源头**（官方原实现/论文/上游 issue 区），不能用另一个第三方移植；发现上游有同类缺陷时，先搜上游 issue。反面同样成立：另一个实现（官方预编译 exe）是最好用的黑盒——把可疑变换手工做掉再喂给它，结果变了就能锁定变量。
- **守卫**：无自动化守卫；引擎 pre/post 处理改动先与官方实现逐项对照，验证手法记在工单 40。

### 3.11 AUTO 降噪按文件切档位：两个静默坑（工单 44/45）

- **现象**：① `realcugan-pro` + 降噪「自动」（当时该模型默认就是「自动」；工单 49 起默认「高」且不再提供「自动」档）在带 JPEG 伪影的图上让引擎抛 `std::out_of_range` → `std::terminate`，DLL 拖垮 GUI；② 批量 AUTO 中「脏图在前、干净图在后」时，干净图沿用脏图的权重变体出图，文件名却写 `-n0`。
- **根源**：① AUTO 的合法性检查只问「1/2/3 档**存在任意一个**」，而按文件估计出的档位要用 `mi.denoise.at()` 查表 —— `realcugan-pro` 只有 无/高 两档，`at(1)` 直接抛异常，且 `iu_run` 无 try/catch；② 权重重载条件只比较**倍数**，AUTO 下 `denoise_level` 恒为 0，导致「本文件 0 档」不触发重载；而 `impl.noise` 只作 `-1` 哨兵、**不参与选权重**，命名与 `configure` 却按本文件档位走。
- **教训**：① 任何「值来自另一个集合」的查表都要先 `find` 再取值，`.at()` 在无异常边界的 DLL 导出面上等于定时炸弹；②「按文件变化的量」必须与「决定加载哪份权重的量」一一对应，重载条件漏掉一项就是静默错配（图错了，名字对）；③ AUTO 这类「运行期才解析出具体值」的功能，能力检查必须按**完整档位集合**而不是「有任意一档」。
- **守卫**：`resolve_model_files` 返回 bool（查不到档位即报错，退出码 2）；重载条件加入 `loaded_denoise`；AUTO 要求 无/低/中/高 四档齐备，不连续档位的模型（如 realcugan-pro）GUI 不提供「自动」项。建议补测试：AUTO 目录中 0 档产物与 `--denoise none` 单文件产物**逐位相同**，以及 pro + auto 的回归用例。

## 4. Windows 工具链（fork / 新机器必读）

构建与发布的依赖，脚本会自动探测，勿手写编译命令：

- **引擎**：VS2022（C++ 桌面开发 + "C++ CMake 工具"组件）与 Vulkan SDK → `scripts\engine-build.bat` 经 vswhere 自动定位；便携/非标准 VS 安装（vswhere 查不到）设环境变量 `IU_VS_PATH`，cmake 异常另设 `IU_CMAKE`
- **GUI**：.NET 8 SDK → `package.ps1` 自动探测（`IU_DOTNET` > PATH > 常见位置，以 `--list-sdks` 验证 8.x）
- **发布**：`powershell -ExecutionPolicy Bypass -File scripts\package.ps1 -Version vX.Y.Z`（零删除，输出 `dist\vX.Y.Z\`）

跨机器通用的坑：

- **.bat 文件只写 ASCII**：cmd 按 ANSI 码页解析 batch，UTF-8 中文注释被误读后可能吞掉换行、把多行拼成一行执行（症状：报"某行中段 不是内部或外部命令"）。报错信息用英文。
- **PATH 上的 dotnet 可能只是运行时**：`dotnet build` 报"下载 .NET SDK"即是；用 `dotnet --list-sdks` 验证是否有 8.x。SDK 可能装在非标准位置（不在 package.ps1 的常见位置探测列表内）：用 `--list-sdks` 逐个验证候选 dotnet.exe，找到后设 `IU_DOTNET` 指向它，再跑构建/打包。
- **Git Bash 调 cmd**：`cmd /c` 的 `/c` 被路径转换吃掉 → 用 `cmd //c "D:\\完整\\路径.bat"`。
- **PowerShell 5.1 + 含中文的 .ps1**：无 BOM 的 UTF-8 被按 ANSI 解析、中文注释炸语法 → .ps1 存成 UTF-8 with BOM。
- **测试跑法**：`python -m pytest tests -q`；测试统一 `-g -1`（CPU 后端）保证确定性，GPU 只留 smoke。conftest 默认找 `bld/image-upscale.exe`（`IU_ENGINE` 仍可覆盖）；以前必须先设 `IU_ENGINE`，是因为默认路径写成了 `build/Release/`（本布局不存在）→ 全部用例静默 skip、pytest 仍全绿（假绿）；现在引擎缺失会在会话末尾红色告警。
- **GitHub 单文件 100MB 上限会拒推整个分支**（v0.2.2 发布）：`git add -A` 把 `.tmp-publish/` 里的 146MB exe 扫进历史，后续虽删但 blob 仍在 → push 被 pre-receive 拒。远端未收到时用 `git filter-branch --index-filter "git rm -r --cached --ignore-unmatch <路径>" -- <上次tag>..main` 重写未推送区段：树未被该文件影响的提交 SHA 不变，受影响的后代提交会全部换 SHA（changelog 里的链接要重新生成）；已推送后才发现就只能 BFG/filter-repo。预防：发版前 `git log --all -- <临时目录>/` 检查，`.gitignore` 覆盖临时目录。

### 3.12 搬测试助手时别把紧邻的装饰器一起删（工单 50 r2）

- **现象**：为消除重复代码把 `make_gradient` / `resolved_levels` 搬进 `tests/conftest.py`，diff 的删除块把紧随其后的 `@needs_engine` 一并吞掉 → 引擎未构建时该用例从 skip 变 error，破坏 conftest 的「不假绿 / skip 必须显式可见」设计。
- **教训**：被删代码块与紧邻的装饰器/注解之间没有视觉分隔，删除前逐行看块尾；测试基建改动后必须实测「缺依赖时是 skip 还是 error」，而不是只看全绿。
- **守卫**：`tests/test_auto.py` 的 `@needs_engine`；改测试基建后跑一次「改名引擎 exe → 期望 skipped」。

### 3.13 评审报出的「理论风险」先用探针证明可达性（工单 50）

- **现象**：两轴评审在同一行代码上给出相反的风险判断（一方说大小写折叠过严、另一方说 locale 依赖会漏检进而覆盖源图）。实测（`cl /W4` 探针 + CLI 复现矩阵）证明该路径**不可达**：`weakly_canonical` 会把同一文件解析回盘上真实大小写，两条比较串逐字符相同，大小写折叠根本不参与。
- **教训**：① 评审的推理可以是对的、结论仍是不可达的——先在真实产物上做探针再决定动刀；② 修法即使保留（去掉 locale 依赖本身正确），**也不得记成红→绿证据**：证据与票面要写明「改前即绿、该风险不可达」，否则等于伪造验证；③ 跨平台路径比较用 `CompareStringOrdinal(..., TRUE)`（Windows）/ 窄字符实现，不要用 `towlower`——它的结果依赖进程 locale。
- **备注**：承载该守卫的代码已由工单 58 整体删除，本条留下的是「先证可达性」的评审纪律与路径比较口径。
- **守卫**：无自动化守卫（代码已删）；靠本条的评审纪律。

### 3.14 记忆文档的授权范围要逐条对齐（工单 49 r2）

- **现象**：修复轮处置清单里写了「顺带订正 `docs/lessons.md` §3.11 那条过时括注」，但维护者批准的只有 §2.4 的改写 → standards 轴判 P1 硬违规（违反「记忆维护必须先提案确认」），该行被原文撤回。
- **教训**：「这条改动是已批准改动的连带修正」不构成授权。授权的节/条目必须逐条对齐，越出批准范围的顺带订正一律先列出来问；写实施者处置清单时，涉及 `AGENTS.md` / `docs/lessons.md` 的改动要单独标注「已获批准的范围是哪个节」。
- **守卫**：无自动化守卫；`AGENTS.md`「记忆维护规则」+ 修复轮处置清单里对记忆文档改动的范围标注。
