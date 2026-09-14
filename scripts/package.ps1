# 打包 portable zip（工单 09）——零删除版本
# 产物：dist/Image-Upscale-win64.zip（解压即用，GUI self-contained）
# 说明：dist/ 目录已存在时由调用者自行清理（本脚本不做递归删除）
$ErrorActionPreference = 'Stop'

$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dist = Join-Path $repo 'dist'
$pkg = Join-Path $dist 'Image-Upscale'
$dotnet = 'D:\Software\DotNet\dotnet.exe'

# 1) 引擎（Release，增量构建）
& cmd /c "D:\tmp\image-upscale-setup\build.bat" | Out-Null
if (-not (Test-Path (Join-Path $repo 'bld\image-upscale.exe'))) { throw 'engine build failed' }

# 2) GUI self-contained 发布（直出目标目录）
& $dotnet publish (Join-Path $repo 'gui\ImageUpscaleGui.csproj') -c Release -r win-x64 --self-contained true -o $pkg
if ($LASTEXITCODE -ne 0) { throw 'gui publish failed' }

# 3) 组装
Copy-Item (Join-Path $repo 'bld\image-upscale.exe') $pkg -Force
Copy-Item (Join-Path $repo 'models') $pkg -Recurse -Force
Copy-Item (Join-Path $repo 'LICENSE') $pkg -Force
Copy-Item (Join-Path $repo 'NOTICE.md') $pkg -Force
Copy-Item (Join-Path $repo 'README.md') $pkg -Force

# 4) 压缩（同名 zip 已存在时要求调用者先清理，避免覆盖删除）
$zip = Join-Path $dist 'Image-Upscale-win64.zip'
if (Test-Path $zip) { throw "zip already exists: $zip（请手动清理后重试）" }
Compress-Archive -Path $pkg -DestinationPath $zip
Write-Output "packaged: $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"
