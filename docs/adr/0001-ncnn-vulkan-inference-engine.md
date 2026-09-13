---
status: accepted
---

# 0001 - 推理引擎采用 ncnn + Vulkan，引擎独立成 exe

waifu2x-caffe 死于绑死旧版 Caffe/CUDA：新显卡（RTX 50 系需 CUDA 12.8+）无法运行，且上游停更。本项目把推理完全交给 ncnn（Vulkan 后端 + CPU 后端），模型统一为 ncnn `.param/.bin` 格式，推理引擎编译为独立 exe（GUI 通过进程调用它）。这样 N/A/Intel 全 vendor 通用、不受 CUDA 版本绑架、CLI 免费获得，代价是放弃 DAT/SwinIR 等 transformer 架构模型（ncnn 上无法高效运行）与 PyTorch 生态的模型即插即用。

## Considered Options

- **PyTorch + CUDA**：模型生态最强，但重蹈 waifu2x-caffe 覆辙（CUDA 版本锁死、体积巨大），否决。
- **ONNX Runtime + DirectML**：能跑 transformer 模型、同样全 vendor，但双引擎维护成本与包体积翻倍，且 NCNN 系模型生态（Upscayl、nihui 系）已覆盖首批全部模型；若未来确需 DAT 类模型（如 Manga-Ora）再评估双引擎，否决。
- **同进程库 + GUI 直连**：省进程开销，但 CLI 要另写、GUI 崩溃拖累推理、引擎无法被第三方脚本独立使用，否决。
