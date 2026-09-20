# AGENTS.md

## Project memory（开工必读）

**每次会话开始、以及改动以下区域之前，先读 `docs/lessons.md`**（历史踩坑：引擎 elempack 契约、Mat 生存期、输出编码、models 定位、GUI 主题/拖拽/布局、构建工具链备忘）：

- 改引擎输出、ncnn::Mat 生命周期、models 定位 → lessons §1
- 改 GUI 控件布局、拖拽、降噪判据、setting.ini → lessons §2
- 打包发布、写回归测试、本机工具链问题 → lessons §3/§4

**创意/UI 类需求（LOGO、图标、配色、布局、字体等视觉与体验决策）先出方案，维护者确认后才进入下一步**（接入/构建/打包/提交均算下一步）。

### Build / test / package 速查

- 引擎构建：`scripts\engine-build.bat`（标准 VS 安装零配置；便携/非标准 MSVC 设 `IU_VS_PATH`，勿手写编译命令）。判定法：该目录下要有 `VC\Auxiliary\Build\vcvars64.bat`；cmake 找不到时另设 `IU_CMAKE`
- 测试：先 `set IU_ENGINE=<仓库>\bld\image-upscale.exe`，再 `python -m pytest tests -q`（conftest 默认路径在本布局不存在；lessons §4）
- 打包：`pwsh -ExecutionPolicy Bypass -File scripts\package.ps1 -Version vX.Y.Z`（零删除，输出 `dist\vX.Y.Z\`；重新发布用新版本号，不删旧包）。非标准 dotnet 安装设 `IU_DOTNET`，指向的 `dotnet.exe` 必须能 `--list-sdks` 列出 8.x（PATH 上的常只有运行时）
- **本机覆盖值不入库**：某台机器需要固定的 `IU_VS_PATH` / `IU_CMAKE` / `IU_DOTNET` / `VULKAN_SDK` 时，写在本机笔记 `.pi/local-env.md`（`.gitignore` 已覆盖 `.pi/`，不随仓库公开），不要写进本文件或其它公开文档。
- **临时文件统一放仓库根**：构建、测试、发布与会话产生的中间物一律放在**仓库根目录**（命名 `.tmp-<用途>` 或 `.tmp-<用途>.<ext>`，`.gitignore` 的 `.tmp-*` 已覆盖），不要写到盘符根目录或系统/自定义 tmp 目录；仓库外已产生的临时文件用完即清。

**记忆维护规则（`AGENTS.md` 本文件与 `docs/lessons.md`）**：

- 更新前必须先向维护者提案确认，不得擅自写入。
- 随仓库公开（clone / fork / build 用户均可见），禁止写入本机特定信息（绝对路径、盘符、机器名、环境变量实际值等），只写对所有环境通用可复现的描述。
- **发布前确认（固定流程）**：push、打 tag、GitHub Release 等一切对外发布动作，必须先列明发布内容（版本号、tag、Release notes、资产）请维护者明确同意后才能执行，不得擅自发布。
- **发布前一次对清（固定流程）**：请求发布确认时，必须把本轮**所有未决项一次列全并定稿**——待维护者决策的改动、待推送的提交、待补的工单状态、Release notes 全文；维护者同意后一次执行完。发布后不得再因遗漏项回头找维护者确认（发布后只允许修 bug 级补救）。
- **Release notes 版式（固定流程）**：简介 + 使用 + 功能 三节**逐字沿用 v0.2.4**（不改写、不加也不减功能条目，历史版本往回对齐时同样处理），只更换 Changelog；Changelog 只写该版用户可见变化，工程/内部改动不进 notes。
- **发布前清理（固定流程）**：发出发布请求前，列清本次迭代产生的临时物（.tmp-publish、pytest 缓存、.scratch 已否决候选存档、无用脚本等），按全局删除安全规则经维护者确认后删除，再请求发布。dist 旧版本目录按零删除原则保留，不属清理对象。
- **测试后 dist 只留压缩包**：解压验证/冒烟完成后，删除 `dist/<版本>/Image-Upscale/` 解压文件夹，只保留 zip（含旧版本归档；删除前仍按全局规则列路径确认）。package.ps1 的零删除原则只约束打包动作本身，不约束本清理步骤。
- **小问题当轮提、不单开票、不单跑轮（固定流程）**：评审/自检报出的 report-only 级小问题（一行注释措辞、补一个测试用例、文档口径统一、重复代码清理、命名/单一定义来源之类）**发现即报**——当轮就把「是什么 / 影响面 / 修法 / 耗时」列给维护者，**不得攒到发布之后才提**（维护者 2026-09-20 定：留着发布后再来提不可接受）。处置：① 由维护者定「本轮收 / 攒批 / 不做」，**默认倾向本轮收**，只有维护者明确说「留到下一版」才攒批；② 攒批的候选票按**同一文件或同一区域**归成一批，实施时**一批一次闭环**（一次实施 + 一次双轴评审 + 一次门禁/打包），不按票各跑一轮；能顺手做进「正好要动那块代码」的票里更好。理由：每轮修复的固定成本（尤其打包与评审）远大于这类小问题的收益，所以要**批量，不要延后**。

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical triage roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
