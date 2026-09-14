# 打包 portable zip（工单 09 / 工单 16）
# 产物：dist/<Version>/Image-Upscale-win64.zip（解压即用，GUI self-contained 单文件）
# 布局（工单 16）：根目录仅 GUI exe + engine/ + models/ + 许可文档；语言资源仅中文
# 说明：不做任何删除操作——输出到版本化子目录，旧包由人工处置
param(
    [string]$Version = 'v0.2'
)
$ErrorActionPreference = 'Stop'

$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dist = Join-Path $repo "dist\$Version"
$pkg = Join-Path $dist 'Image-Upscale'
# dotnet 探测：IU_DOTNET 环境变量 > PATH > 常见位置；必须含 .NET 8 SDK（PATH 上的可能只是运行时）
function Find-DotNet {
    if ($env:IU_DOTNET -and (Test-Path $env:IU_DOTNET)) { return $env:IU_DOTNET }
    $cands = @()
    $cmd = Get-Command dotnet -ErrorAction SilentlyContinue
    if ($cmd) { $cands += $cmd.Source }
    $cands += @(Join-Path $env:ProgramFiles 'dotnet\dotnet.exe')
    if ($env:LOCALAPPDATA) { $cands += (Join-Path $env:LOCALAPPDATA 'Microsoft\dotnet\dotnet.exe') }
    foreach ($c in $cands) {
        if (-not $c -or -not (Test-Path $c)) { continue }
        $sdks = & $c --list-sdks 2>$null
        if ($sdks | Where-Object { $_ -match '^8\.' }) { return $c }
    }
    throw '未找到 .NET 8 SDK：PATH 上的 dotnet 可能只是运行时（用 dotnet --list-sdks 验证），或设置环境变量 IU_DOTNET 指向 SDK 的 dotnet.exe'
}
$dotnet = Find-DotNet

if (Test-Path (Join-Path $dist 'Image-Upscale-win64.zip')) { throw "zip already exists: $dist\Image-Upscale-win64.zip（换一个 -Version）" }

# 1) 引擎（Release，增量构建；构建入口已收编进 scripts/engine-build.bat）
& cmd /c (Join-Path $repo 'scripts\engine-build.bat') | Out-Null
if (-not (Test-Path (Join-Path $repo 'bld\image-upscale.exe'))) { throw 'engine build failed' }

# 2) GUI self-contained 单文件发布（csproj 内含 PublishSingleFile / SatelliteResourceLanguages=zh-Hans）
& $dotnet publish (Join-Path $repo 'gui\ImageUpscaleGui.csproj') -c Release -r win-x64 -o $pkg
if ($LASTEXITCODE -ne 0) { throw 'gui publish failed' }

# 3) 组装：根目录仅 GUI exe + engine/ 子目录 + models/ + 许可文档
New-Item -ItemType Directory -Force (Join-Path $pkg 'engine') | Out-Null
Copy-Item (Join-Path $repo 'bld\image-upscale.exe') (Join-Path $pkg 'engine\image-upscale.exe') -Force
Copy-Item (Join-Path $repo 'models') $pkg -Recurse -Force
Copy-Item (Join-Path $repo 'LICENSE') $pkg -Force
Copy-Item (Join-Path $repo 'NOTICE.md') $pkg -Force
Copy-Item (Join-Path $repo 'README.md') $pkg -Force

# 4) 压缩
$zip = Join-Path $dist 'Image-Upscale-win64.zip'
Compress-Archive -Path $pkg -DestinationPath $zip
Write-Output "packaged: $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"
