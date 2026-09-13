# Image-Upscale

本地图像超分辨率工具（GUI + CLI 同核），waifu2x-caffe 的现代继任者：推理基于 ncnn + Vulkan，N/A/Intel 全 vendor 显卡通用并有 CPU 兜底。

术语表见 [CONTEXT.md](./CONTEXT.md)；关键决策见 [docs/adr/](./docs/adr/)；规格与工单见 [.scratch/image-upscale/](./.scratch/image-upscale/)。

## 当前状态

工单 01（引擎端到端超分链路）实施中。

## 构建（Windows）

前置：Visual Studio Build Tools 2022（C++ 桌面开发）、Vulkan SDK、CMake（Build Tools 自带）。

```powershell
git submodule update --init --recursive
cmake -S . -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
```

产物：`build/Release/image-upscale.exe`

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
