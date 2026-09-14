# Image-Upscale

本地图像超分辨率工具（GUI + CLI 同核），waifu2x-caffe 的现代继任者：推理基于 ncnn + Vulkan，Nvidia/AMD/Intel 显卡通用并有 CPU 兜底。**本项目全程由 AI 开发。**

术语表见 [CONTEXT.md](./CONTEXT.md)；关键决策见 [docs/adr/](./docs/adr/)；踩坑清单见 [docs/lessons.md](./docs/lessons.md)；规格与工单见 [.scratch/image-upscale/](./.scratch/image-upscale/)。

## 当前状态

**v0.2.1 已发布**：从 [Releases](https://github.com/CC-3301/Image-Upscale/releases/latest) 下载 zip 解压即用（根目录仅 GUI exe + engine/ + models/）。

后续迭代工单见 [.scratch/image-upscale/issues/](./.scratch/image-upscale/issues/)；全部工单状态以文件内 `Status:` 行为准。

## 构建（Windows）

前置：Visual Studio 2022（C++ 桌面开发 + "C++ CMake 工具"组件）、Vulkan SDK、.NET 8 SDK。标准安装下脚本自动探测工具链；便携/非标准安装用环境变量覆盖（`IU_VS_PATH` / `IU_CMAKE` / `IU_DOTNET`），详见 [docs/lessons.md](./docs/lessons.md) 的「Windows 工具链」一节。

```powershell
git submodule update --init --recursive

# 引擎（ncnn + Vulkan + CPU）
scripts\engine-build.bat          # 产物：bld\image-upscale.exe

# GUI（WPF，.NET 8）
dotnet build gui\ImageUpscaleGui.csproj -c Release

# 一键打包 portable zip（含引擎/GUI/模型，输出 dist\vX.Y.Z\）
powershell -ExecutionPolicy Bypass -File scripts\package.ps1 -Version v0.2.1
```

## 模型获取

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch-models.ps1
```

## 引擎 CLI

```text
image-upscale -i input-path [-m model-name] [-s 2.0] [-f jpg|png|webp] [-q 0-100] [-t tile] [-g gpu-id] [-v]
```

- 输入为单文件：输出 `A-(模型名)-2.0x.后缀`（同目录）
- 输入为文件夹：输出同级文件夹 `A-(模型名)-2.0x/`（文件名保留）
- 默认 JPG 质量 90；输出格式不跟随输入格式
- 退出码：0 成功 / 1 参数错误 / 2 模型或推理失败 / 3 IO 错误
- 进度：stdout 行式 `progress <done>/<total>`，结束输出 `done`

## 许可

代码 MIT；第三方组件与打包模型许可见 [NOTICE.md](./NOTICE.md)。
