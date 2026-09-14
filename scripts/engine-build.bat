@echo off
rem Engine build entry (used by scripts/package.ps1 and manual builds).
rem Requirements: VS2022 (C++ desktop workload + CMake component) and Vulkan SDK.
rem Discovery order: env overrides (IU_VS_PATH / IU_CMAKE / VULKAN_SDK) -> vswhere.
rem NOTE: keep this file ASCII-only. cmd parses .bat via ANSI codepage; UTF-8
rem       comments get misread and can swallow newlines, breaking the script.
setlocal enabledelayedexpansion

rem --- 1) locate vcvars64 ---
set "VCVARS="
if defined IU_VS_PATH if exist "%IU_VS_PATH%\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%IU_VS_PATH%\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS (
    set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
    if exist "!VSWHERE!" for /f "usebackq delims=" %%i in (`"!VSWHERE!" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do if exist "%%i\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%i\VC\Auxiliary\Build\vcvars64.bat"
)
if not defined VCVARS (
    echo [engine-build] ERROR: cannot find vcvars64.bat
    echo [engine-build] Install VS2022 with the "Desktop development with C++" workload,
    echo [engine-build] or set env var IU_VS_PATH to your VS installation directory.
    exit /b 1
)
set "VSDIR=!VCVARS:\VC\Auxiliary\Build\vcvars64.bat=!"

rem --- 2) locate cmake ---
set "CMAKE="
if defined IU_CMAKE if exist "%IU_CMAKE%" set "CMAKE=%IU_CMAKE%"
if not defined CMAKE if exist "!VSDIR!\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" set "CMAKE=!VSDIR!\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
if not defined CMAKE for /f "delims=" %%i in ('where cmake 2^>nul') do if not defined CMAKE set "CMAKE=%%i"
if not defined CMAKE (
    echo [engine-build] ERROR: cannot find cmake.exe
    echo [engine-build] Install the "C++ CMake tools" component in VS, add cmake to PATH,
    echo [engine-build] or set env var IU_CMAKE to the full cmake.exe path.
    exit /b 1
)

rem --- 3) Vulkan SDK (its installer sets VULKAN_SDK automatically) ---
if not defined VULKAN_SDK (
    echo [engine-build] ERROR: VULKAN_SDK env var not found
    echo [engine-build] Install the Vulkan SDK: https://vulkan.lunarg.com/sdk/home
    exit /b 1
)
set "PATH=%VULKAN_SDK%\Bin;!VSDIR!\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;%PATH%"

call "!VCVARS!" >nul
if errorlevel 1 (
    echo [engine-build] ERROR: vcvars64 initialization failed
    exit /b 1
)

set "REPO=%~dp0.."
echo === configure (ninja, forced layer flags) ===
"!CMAKE!" -S "%REPO%" -B "%REPO%\bld" -G Ninja -DCMAKE_BUILD_TYPE=Release -DWITH_LAYER_crop=ON -DWITH_LAYER_flatten=ON -DWITH_LAYER_pooling=ON -DWITH_LAYER_scale=ON -DWITH_LAYER_padding=ON -DWITH_LAYER_interp=ON -DWITH_LAYER_cast=ON -DWITH_LAYER_split=ON -DWITH_LAYER_binaryop=ON -DWITH_LAYER_concat=ON -DWITH_LAYER_pixelshuffle=ON -DWITH_LAYER_prelu=ON
echo === build ===
"!CMAKE!" --build "%REPO%\bld"
