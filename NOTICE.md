# Third-party notices

本仓库的引擎代码部分适配自以下 MIT 许可项目：

- **nihui/waifu2x-ncnn-vulkan**（https://github.com/nihui/waifu2x-ncnn-vulkan）
  - `engine/src/waifu2x.cpp` / `waifu2x.h`：tiled 推理内核
  - `engine/src/filesystem_utils.h` / `win32dirent.h`：路径工具
  - `engine/src/waifu2x_*.comp` + `generate_shader_comp_header.cmake`：compute shader 与内嵌脚本
- **nihui/realcugan-ncnn-vulkan**（https://github.com/nihui/realcugan-ncnn-vulkan）
  - `engine/src/realcugan.cpp` / `realcugan.h` 与配套 shader：CUGAN 架构 tiled 推理内核
  - `engine/src/stb_image.h` / `stb_image_write.h`（nothings/stb，公有领域）
- **xinntao/Real-ESRGAN-ncnn-vulkan**（https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan）
  - `engine/src/realesrgan.cpp` / `realesrgan.h` 与配套 shader：RRDB/Compact 架构 tiled 推理内核（含自研 CPU 路径）
- **xinntao/Real-ESRGAN**（BSD-3）：`scripts/convert-general-x4v3.py` 使用其 SRVGGNetCompact 架构与官方权重（base/wdn 对）经 pnnx 转换出 general-x4v3 四个降噪变体
- 其余依赖以其自身许可证声明：
  - **Tencent/ncnn**（BSD 3-Clause，git submodule）
  - **webmproject/libwebp**（BSD 3-Clause，git submodule）

打包模型（models/，不入库）的许可出处见 README.md 的模型清单表。
