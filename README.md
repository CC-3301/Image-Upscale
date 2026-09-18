# Image-Upscale

本地图像超分辨率工具，waifu2x-caffe 的现代继任者：推理基于 ncnn + Vulkan，Nvidia/AMD/Intel 显卡通用并有 CPU 兜底。**本项目全程由 AI 开发。**

术语表见 [CONTEXT.md](./CONTEXT.md)；关键决策见 [docs/adr/](./docs/adr/)；踩坑清单见 [docs/lessons.md](./docs/lessons.md)；规格与工单见 [.scratch/image-upscale/](./.scratch/image-upscale/)。

## 当前状态

**已发布**：从 [Releases](https://github.com/CC-3301/Image-Upscale/releases/latest) 下载最新 zip 解压即用（根目录仅 `ImageUpscale.exe` + `models/` + `NOTICE.md`，引擎已融合进单文件；MIT 许可与第三方声明见包内 NOTICE.md，完整文档见仓库）。

后续迭代工单见 [.scratch/image-upscale/issues/](./.scratch/image-upscale/issues/)；全部工单状态以文件内 `Status:` 行为准。

## 构建（Windows）

前置：Visual Studio 2022（C++ 桌面开发 + "C++ CMake 工具"组件）、Vulkan SDK、.NET 8 SDK。标准安装下脚本自动探测工具链；便携/非标准安装用环境变量覆盖（`IU_VS_PATH` / `IU_CMAKE` / `IU_DOTNET`），详见 [docs/lessons.md](./docs/lessons.md) 的「Windows 工具链」一节。

```powershell
git submodule update --init --recursive

# 引擎（ncnn + Vulkan + CPU）→ bld\iu_engine.dll
# （另有测试缝薄壳 bld\image-upscale.exe，仅自动化测试用，不随发布分发）
scripts\engine-build.bat

# GUI（WPF，.NET 8）→ ImageUpscale.exe
dotnet build gui\ImageUpscaleGui.csproj -c Release

# 一键打包 portable zip（引擎融合进单文件，输出 dist\vX.Y.Z\）
powershell -ExecutionPolicy Bypass -File scripts\package.ps1 -Version vX.Y.Z
```

## 模型获取

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch-models.ps1
```

## 使用

解压后运行 `ImageUpscale.exe`：

- 输入支持拖入或浏览文件/文件夹（文件夹为递归批处理，仅顶层重命名，内部结构原样镜像）
- 输出与输入同目录：`A-(模型名)-nN-<倍率|尺寸>.后缀`（N = 0/1/2/3，即实际生效的降噪档位）；目录批处理下自动档逐文件解析，全批同档时目录名写该档位、档位不一致时目录名写 `nX` 且每个产物文件名各带自己的 `-nN`；指定尺寸小于原图时直通缩放（模型位写 `Resize`）
- 降噪档位 自动/无/低/中/高，随模型能力自动启用或灰置；"自动"由伪影启发式估计
- 降采样方式 Lanczos（默认）/ Catmull-Rom / Bicubic / Box：**只用于缩小**（把模型结果缩到你要的精确尺寸、直通缩放）；锐度依次递减：Lanczos（最锐，可能轻微振铃）> Catmull-Rom > Bicubic（= Mitchell-Netravali，无振铃较柔）≈ Box（面积平均，整数倍时等同盒式）；漫画网点建议 Lanczos，怕振铃可退到 Bicubic
- 目标尺寸模式下**放大全部由模型完成，不做插值放大**：模型按原生倍率反复跑直到超过目标，最后只做缩小（对齐 waifu2x）；例如 2x 模型要 3 倍会跑两遍模型得到 4 倍再缩到 3 倍。代价：目标倍率越大轮数越多，耗时与内存随之增长
- 输出格式 JPG（默认质量 90）/ PNG / WebP，质量 0-100 可调；输出格式不跟随输入格式
- 退出码语义由引擎内部保留（0 成功 / 1 参数错误 / 2 推理失败 / 3 IO 错误），GUI 据此提示

## 许可

代码 MIT；第三方组件与打包模型许可见 [NOTICE.md](./NOTICE.md)。
