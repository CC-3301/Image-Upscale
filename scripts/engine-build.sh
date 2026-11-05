#!/usr/bin/env bash
# 引擎构建入口（Linux/POSIX）。编译参数与 scripts/engine-build.bat 保持一致。
#
# 依赖：cmake(>=3.16)、ninja、C++17 编译器（gcc/clang）、Vulkan 开发头文件。
#   按发行版安装，例如 Debian/Ubuntu：sudo apt install cmake ninja-build libvulkan-dev
# 可覆盖的环境变量：IU_CMAKE（cmake 路径）、IU_NINJA（ninja 路径）、IU_BUILD_DIR（构建目录）。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CMAKE="${IU_CMAKE:-cmake}"
BUILD_DIR="${IU_BUILD_DIR:-$REPO/bld}"

if ! command -v "$CMAKE" >/dev/null 2>&1; then
    echo "[engine-build] ERROR: cmake not found (install cmake or set IU_CMAKE)" >&2
    exit 1
fi
if ! command -v ninja >/dev/null 2>&1; then
    echo "[engine-build] ERROR: ninja not found (install ninja-build)" >&2
    exit 1
fi
if ! pkg-config --exists vulkan 2>/dev/null && [ -z "${VULKAN_SDK:-}" ]; then
    echo "[engine-build] WARN: 未检测到 Vulkan 开发包（pkg-config vulkan / VULKAN_SDK）；" >&2
    echo "[engine-build]       configure 会因 find_package(Vulkan) 失败，请安装 libvulkan-dev" >&2
fi

echo "=== configure (ninja, forced layer flags) ==="
"$CMAKE" -S "$REPO" -B "$BUILD_DIR" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DNCNN_DISABLE_EXCEPTION=OFF \
    -DWITH_LAYER_crop=ON -DWITH_LAYER_flatten=ON -DWITH_LAYER_pooling=ON \
    -DWITH_LAYER_scale=ON -DWITH_LAYER_padding=ON -DWITH_LAYER_interp=ON \
    -DWITH_LAYER_cast=ON -DWITH_LAYER_split=ON -DWITH_LAYER_binaryop=ON \
    -DWITH_LAYER_concat=ON -DWITH_LAYER_pixelshuffle=ON -DWITH_LAYER_prelu=ON

echo "=== build ==="
"$CMAKE" --build "$BUILD_DIR" --parallel

echo "[engine-build] done: $BUILD_DIR/image-upscale"
