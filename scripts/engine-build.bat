@echo off
rem 引擎构建入口（供 scripts/package.ps1 与手动构建使用）
rem 原 D:\tmp\image-upscale-setup\build.bat 收编入库，路径改为仓库相对
set VULKAN_SDK=D:\Software\VulkanSDK
set PATH=%VULKAN_SDK%\Bin;%PATH%
call "D:\Software\MSVC\VC\Auxiliary\Build\vcvars64.bat" >nul
set REPO=%~dp0..
set "CMAKE=D:\Software\MSVC\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
echo === configure (ninja, forced layer flags) ===
"%CMAKE%" -S "%REPO%" -B "%REPO%\bld" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_MAKE_PROGRAM="D:\Software\MSVC\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe" -DWITH_LAYER_crop=ON -DWITH_LAYER_flatten=ON -DWITH_LAYER_pooling=ON -DWITH_LAYER_scale=ON -DWITH_LAYER_padding=ON -DWITH_LAYER_interp=ON -DWITH_LAYER_cast=ON -DWITH_LAYER_split=ON -DWITH_LAYER_binaryop=ON -DWITH_LAYER_concat=ON -DWITH_LAYER_pixelshuffle=ON -DWITH_LAYER_prelu=ON
echo === build ===
"%CMAKE%" --build "%REPO%\bld"
