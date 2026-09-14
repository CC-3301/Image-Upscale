# License & Third-party notices

## 本软件许可（MIT）

MIT License

Copyright (c) 2026 Image-Upscale contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Third-party notices

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
