# 09: portable zip 发布

**Parent:** .scratch/image-upscale/spec.md

**What to build:** 用户从 release 下载一个 zip，解压即用：GUI self-contained 发布（目标机器无需安装 .NET Runtime）+ 引擎 exe + models 目录 + MIT LICENSE + README（模型清单及各自许可出处、导入自定义模型的方法）。在一台没有任何开发库的干净 Windows 上可用。

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] zip 解压后无需安装任何运行时即可运行 GUI 与 CLI
- [ ] 全部打包模型随包分发，models 目录结构支持放入自定义 ncnn 模型即被识别
- [ ] 仓库根目录 MIT LICENSE；README 含模型许可出处表与导入说明
- [ ] 干净 Windows 环境（无 Vulkan SDK、无 .NET、无编译器）冒烟：GUI 单图 + 文件夹各跑通一次
- [ ] 引擎在无 Vulkan 设备的机器上回退 CPU 可用
