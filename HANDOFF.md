# HANDOFF

接手本仓库前先读 `AGENTS.md`（构建/测试/打包/发布流程）与 `docs/lessons.md`（历史踩坑）。

## 当前状态

v0.3.2 的三个需求已实现并合入 `main`，引擎侧门禁全绿（149 passed / 12 skipped）。**GUI 未在本机构建，待 Windows 打包后人工验收。**

## 本批交付

- LOGO 重制：石墨黑 `#24262B` + 白色几何 IU、字母占比 55%，替换 `app.png` / `app.ico`；生成脚本 `scripts/make-app-icon.py`。
- 添加后缀四态：引擎 `--suffix both|folder|file|none`（`--no-rename` 保留为 `none` 同义），GUI 下拉，`LastAddSuffix` 旧值迁移。
- 序列化重命名：引擎 `--sequence`，产物按资源管理器口径编号 `001…`，源文件名不变；写盘走 `<目标名>.iu-tmp`，顺序为「写 tmp → 删源 → 改名」。

## 待办

1. **Windows 上打包验收**：`pwsh -ExecutionPolicy Bypass -File scripts\package.ps1 -Version v0.3.2`，产物在 `dist\v0.3.2\`。
2. 人工验收项：三个下拉不换行、四态产物命名、序列化编号、exe 与窗口图标。
3. 验收通过后再决定是否推送与打 tag。

## 协作约束

- 新功能先讨论、明确因果链再落地；未确认不写代码。
- 界面/设计类改动先出预览让维护者确认。
- 临时文件写仓库根目录 `.tmp-*`；不写入盘符根或系统临时目录。
- 删除须先列明确路径并获当次确认；写盘被拦截时由维护者输入 `/write-allow`，删除同理 `/delete-allow`。
- 文档与注释不写日期、不写过程叙述，只记事实与规则。

## 验证入口

引擎构建 `scripts/engine-build.sh`（Linux，脚本无执行位，用 `bash` 调）；测试 `IU_ENGINE=<仓库>/bld/image-upscale python -m pytest tests -q`。
GUI 为 WPF，仅 Windows 可构建与人工验收；引擎行为走 CLI 薄壳的进程边界测试。

## 建议技能

- `implement-auto`：按工单批量落地。
- `tdd`：先写引擎命名行为的失败用例再实现。
- `code-review`：改动完成后按 Standards / Spec 双轴评审。
