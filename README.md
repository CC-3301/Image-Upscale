# Image-Upscale

本地图像超分辨率工具，waifu2x-caffe 的现代继任者：推理基于 ncnn + Vulkan，Nvidia/AMD/Intel 显卡通用并有 CPU 兜底。**本项目全程由 AI 开发。**

术语表见 [GLOSSARY.md](./GLOSSARY.md)；关键决策见 [docs/adr/](./docs/adr/)；踩坑清单见 [docs/lessons.md](./docs/lessons.md)；规格与工单见 [.scratch/image-upscale/](./.scratch/image-upscale/)。

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

## 构建（Linux）

图形界面是 WPF，仅 Windows 提供；Linux 只构建引擎命令行与测试缝（`bld/image-upscale`、`bld/libiu_engine.so`）。

前置：C++17 编译器、CMake ≥ 3.16、Ninja、Vulkan 开发包（如 Debian/Ubuntu 的 `libvulkan-dev`）与 Vulkan 驱动；测试另需 Python 3 与 `pytest` / `Pillow` / `numpy`。

```bash
git submodule update --init --recursive

# 引擎（ncnn + Vulkan + CPU）
scripts/engine-build.sh

# 测试（默认取 bld/image-upscale，可用 IU_ENGINE 覆盖）
python3 -m pytest tests -q
```

模型目录 `models/` 不入库：可手动放置，或安装 PowerShell 7 后执行 `pwsh scripts/fetch-models.ps1`。

## 模型获取

```powershell
powershell -ExecutionPolicy Bypass -File scripts/fetch-models.ps1
```

| 模型（清单 id） | 来源 | 许可 / 再分发 |
| --- | --- | --- |
| `waifu2x_upconv_7_art` / `waifu2x_cunet` / `waifu2x_upconv_7_photo` | nihui/waifu2x-ncnn-vulkan release | MIT |
| `realcugan-pro` / `realcugan-se` | nihui/realcugan-ncnn-vulkan release | MIT |
| `digital-art-4x` | upscayl/upscayl resources | Upscayl 官方允许再分发 |
| `realesr-general-x4v3`（含 `-low` / `-mid` / `-high`） | xinntao/Real-ESRGAN v0.2.5.0 权重经 pnnx 转换 | BSD-3 |

### 导入自己的模型

1. 在 `models/` 下新建子目录（目录名与下面的 `dir` 一致），放入 ncnn 转换出的 `.param` 与 `.bin`
2. 在 `models/manifest.conf` 追加一块（字段规则见下），保存后重启程序
3. 模型会出现在列表里（按名称 A-Z 排序；不写 `denoise` 时降噪固定为「无」并灰置）

```conf
model my-model            # 必填：清单 id（也是命令行 -m 与 setting.ini 记录的值）
display my-model          # 列表显示名，同时用作产物文件名里的模型段
group general             # 分组标记（当前界面按 A-Z 平铺，此字段仅作记录）
arch compact              # 推理内核：waifu2x | cugan | rrdb | compact
dir my-model              # models/ 下的子目录名
scale 4                   # 原生倍率，可写多行声明多个倍率
prepad 10                 # 预填充像素：单值 = 所有倍率同值；也可按倍率写 `prepad 2 18`
in data                   # 网络输入 blob 名（取自 .param）
out output                # 网络输出 blob 名（取自 .param）
tileauto realesrgan       # 自动 tile 策略：upconv | cunet | cugan | realesrgan
denoise none my-model     # 档位 none/low/mid/high → 该架构的权重变体 token；不写 = 不支持降噪
```

权重文件名由 `arch` 决定（`<token>` 取自 `denoise` 行）：

| arch | 权重文件（放在 `models/<dir>/` 下） | token 示例 |
| --- | --- | --- |
| `waifu2x` | `noise<token>_scale2.0x_model.param` / `.bin`（仅支持 2x） | `0` / `1` / `2` / `3` |
| `cugan` | `up<倍率>x-<token>.param` / `.bin` | `no-denoise` / `denoise3x` |
| `rrdb` / `compact` | `<token>.param` / `.bin` | 直接就是文件名 |

Real-CUGAN pro 系权重额外加一行 `pro yes`（需官方 [0.15,0.85] 仿射归一化）。
降噪档位「自动」需要该模型 无/低/中/高 **四档齐备**，否则界面不提供「自动」项。

## 使用

解压后运行 `ImageUpscale.exe`：

- 输入支持拖入或浏览文件/文件夹（文件夹为递归批处理，仅顶层重命名，内部结构原样镜像）
- 输出与输入同目录：`A-(模型名)-nN-<倍率|尺寸>.后缀`（N = 0/1/2/3，即实际生效的降噪档位）；目录批处理下自动档逐文件解析，全批同档时目录名写该档位、档位不一致时目录名写 `nX` 且每个产物文件名各带自己的 `-nN`；指定尺寸小于原图时直通缩放（模型位写 `Resize`）
- 降噪档位 自动/无/低/中/高，随模型能力自动启用或灰置；"自动"由伪影启发式估计；档位齐备（无/低/中/高）的模型默认"自动"且**共用一份记忆**（改过就一直记住，重启保持），档位不齐的模型（如 realcugan-pro）默认最高可用档并各自独立记忆，不支持降噪的模型固定"无"
- 添加后缀 开（两者，默认）/ 开（文件夹）/ 开（文件）/ 关：决定 `-(模型名)-nN-<倍率|尺寸>`（直通缩放为 `-(Resize)-<尺寸>`）这段后缀落在哪。**开（两者）**= 输出文件夹名带段、产物文件名按 AUTO 逐文件档位补 `-nN`（与旧版「添加扩展名=开」一致）；**开（文件夹）**= 只输出文件夹名带段、产物文件名永远干净；**开（文件）**= 不建输出目录、产物落源目录且文件名带整段；**关**= 都不带，产物 = 源文件同目录 + 原文件名 + 输出格式扩展名，**产物路径与输入路径相同**时（如 `A.png` 输出 PNG；`A.jpeg` 输出 JPG → 新增 `A.jpg`，不命中）则**原地覆盖源文件**（源图被替换、不可撤销）。开（文件）/关 会把产物写进输入树，二次运行会把上一轮产物当输入再处理一轮；单文件输入没有文件夹可挂段，开（文件夹）与关等价，并在日志末尾提示覆盖。撞车口径：**「序列化重命名」或「删除输入文件」任一打开时一律覆盖、不报错**；两者都关时，产物撞到同批另一个输入、或两个产物算到同一路径（同目录 `1.jpg` + `1.png` 配 `-f jpg`）会在跑之前报错拒绝（退出码 1），不静默盖掉源图。改选「与输入格式相同」时产物扩展名逐文件不同，同 stem 不同扩展名因此不撞
- 序列化重命名 开 / 关（默认）：开启后按现有文件名的自然顺序（与资源管理器一致：数字按大小、字母不分大小写、中文按拼音）给**产物**编号，从 `001` 起、3 位补零（超过 999 自然变 4 位）；每个子文件夹各自从 001 起，子文件夹本身不改名；只有 jpg/jpeg/png/webp 参与。**源文件名全程不变**，编号只落在产物名上（例：`2.jpg 1.jpg 3.jpg` → 产物 `001.png 002.png 003.png`）
- 删除输入文件 开 / 关（默认）：开启后**产物写盘成功才**删掉源文件（写盘失败则源图保留），产物与输入同路径（原地覆盖）时跳过；文件与文件夹输入都生效，文件夹逐文件删。**删除不可逆**，无备份、无二次确认
- 降采样方式 Lanczos（默认）/ Catmull-Rom / Bicubic / Box：**只用于缩小**（把模型结果缩到你要的精确尺寸、直通缩放）；锐度依次递减：Lanczos（最锐，可能轻微振铃）> Catmull-Rom > Bicubic（= Mitchell-Netravali，无振铃较柔）≈ Box（面积平均，整数倍时等同盒式）；漫画网点建议 Lanczos，怕振铃可退到 Bicubic
- 目标尺寸模式下**放大全部由模型完成，不做插值放大**：模型按原生倍率反复跑直到超过目标，最后只做缩小（对齐 waifu2x）；例如 2x 模型要 3 倍会跑两遍模型得到 4 倍再缩到 3 倍。代价：目标倍率越大轮数越多，耗时与内存随之增长
- 输出格式 JPG（默认质量 90）/ PNG / WebP / 与输入格式相同（逐文件跟随，产物扩展名保留输入拼写），质量 0-100 可调；除「与输入格式相同」外不跟随输入格式
- 退出码语义由引擎内部保留（0 成功 / 1 参数错误 / 2 推理失败 / 3 IO 错误），GUI 据此提示

## 许可

代码 MIT；第三方组件与打包模型许可见 [NOTICE.md](./NOTICE.md)。
