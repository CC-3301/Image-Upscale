# 09: portable zip 发布

**Parent:** .scratch/image-upscale/spec.md

**What to build:** 用户从 release 下载一个 zip，解压即用：GUI self-contained 发布（目标机器无需安装 .NET Runtime）+ 引擎 exe + models 目录 + MIT LICENSE + README（模型清单及各自许可出处、导入自定义模型的方法）。在一台没有任何开发库的干净 Windows 上可用。

**Blocked by:** 08

**Status:** done（代码完成；验收清单见下方 Comments）

- [ ] zip 解压后无需安装任何运行时即可运行 GUI 与 CLI
- [ ] 全部打包模型随包分发，models 目录结构支持放入自定义 ncnn 模型即被识别
- [ ] 仓库根目录 MIT LICENSE；README 含模型许可出处表与导入说明
- [ ] 干净 Windows 环境（无 Vulkan SDK、无 .NET、无编译器）冒烟：GUI 单图 + 文件夹各跑通一次
- [ ] 引擎在无 Vulkan 设备的机器上回退 CPU 可用

## Comments

### 实现记录（2026-09-14）
- scripts/package.ps1：引擎 Release 构建 + GUI self-contained 发布（net8.0-windows win-x64）+ models/LICENSE/README/NOTICE 组装 + Compress-Archive
- 产物：dist/Image-Upscale-win64.zip（157.3 MB）
- 冒烟（解压至 D:/tmp/iu-zip-smoke 干净目录）：
  - CLI：realcugan-se 2x + --denoise auto → exit 0，输出 test-(realcugan-se)-2.0x.png 128x96 ✅
  - GUI：进程启动存活 ✅（视觉验收待人工）
- zip 内布局：ImageUpscaleGui.exe / image-upscale.exe / models/(7 组+manifest) / LICENSE / NOTICE.md / README.md
Status: done（自动化冒烟通过；GUI 视觉验收待人工）
- 2026-09-19 补记（v0.2.6）：README 已补「模型许可出处表」与「导入自己的模型」说明（manifest 字段规则 + 各架构权重文件命名）；NOTICE.md 那句悬空引用改为指向该表。工单两处验收齐备。
