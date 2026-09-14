# AGENTS.md

## Project memory（开工必读）

**每次会话开始、以及改动以下区域之前，先读 `docs/lessons.md`**（历史踩坑：引擎 elempack 契约、Mat 生存期、输出编码、models 定位、GUI 主题/拖拽/布局、构建工具链备忘）：

- 改引擎输出、ncnn::Mat 生命周期、models 定位 → lessons §1
- 改 GUI 控件布局、拖拽、降噪判据、setting.ini → lessons §2
- 打包发布、写回归测试、本机工具链问题 → lessons §3/§4

**创意/UI 类需求（LOGO、图标、配色、布局、字体等视觉与体验决策）先出方案，维护者确认后才进入下一步**（接入/构建/打包/提交均算下一步）。

### Build / test / package 速查

- 引擎构建：`scripts\engine-build.bat`（标准 VS 安装零配置；便携/非标准 MSVC 设 `IU_VS_PATH`，勿手写编译命令）
- 测试：先 `set IU_ENGINE=<仓库>\bld\image-upscale.exe`，再 `python -m pytest tests -q`（conftest 默认路径在本布局不存在；lessons §4）
- 打包：`powershell -ExecutionPolicy Bypass -File scripts\package.ps1 -Version vX.Y.Z`（零删除，输出 `dist\vX.Y.Z\`；非标准 dotnet 安装设 `IU_DOTNET`；重新发布用新版本号，不删旧包）
- **发布前清理（固定流程）**：发出发布请求前，列清本次迭代产生的临时物（.tmp-publish、pytest 缓存、.scratch 已否决候选存档、无用脚本等），按全局删除安全规则经维护者确认后删除，再请求发布。dist 旧版本目录按零删除原则保留，不属清理对象。

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical triage roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
