# 打包 portable zip（工单 09 / 16 / 27）
# 产物：dist/<Version>/Image-Upscale-win64.zip（解压即用，单 ImageUpscale.exe，引擎已融合）
# 布局（工单 27）：根目录仅 ImageUpscale.exe + models/ + 许可文档；引擎以 iu_engine.dll 收编进单文件
# 说明：不做任何删除操作——输出到版本化子目录，旧包由人工处置
param(
    [string]$Version = 'v0.2.2'
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
# 产出 bld\iu_engine.dll（随发布收编）与 bld\image-upscale.exe（测试缝薄壳，不分发）
& cmd /c (Join-Path $repo 'scripts\engine-build.bat') | Out-Null
if (-not (Test-Path (Join-Path $repo 'bld\iu_engine.dll'))) { throw 'engine build failed' }

# 2) GUI self-contained 单文件发布（引擎 DLL 经 -p:EngineDll 收编进单文件）
& $dotnet publish (Join-Path $repo 'gui\ImageUpscaleGui.csproj') -c Release -r win-x64 -o $pkg -p:EngineDll="$repo\bld\iu_engine.dll"
if ($LASTEXITCODE -ne 0) { throw 'gui publish failed' }

# 3) 组装 + 守卫（工单 27）：包根仅 ImageUpscale.exe + models/ + 许可文档
New-Item -ItemType Directory -Force (Join-Path $pkg 'models') | Out-Null
Copy-Item (Join-Path $repo 'models\*') (Join-Path $pkg 'models') -Recurse -Force
Copy-Item (Join-Path $repo 'LICENSE') $pkg -Force
Copy-Item (Join-Path $repo 'NOTICE.md') $pkg -Force
Copy-Item (Join-Path $repo 'README.md') $pkg -Force

if (Test-Path (Join-Path $pkg 'iu_engine.dll')) { throw 'iu_engine.dll 未被收编进单文件（包根出现散装 dll，分发形态被破坏）' }
$pdbs = Get-ChildItem $pkg -Filter *.pdb -Recurse
if ($pdbs) { throw "包内出现 pdb：$($pdbs.Name -join ', ')" }
$exes = Get-ChildItem $pkg -Filter *.exe -Recurse
if ($exes.Count -ne 1 -or $exes[0].Name -ne 'ImageUpscale.exe') { throw "包根应仅有一个 ImageUpscale.exe，实际：$($exes.Name -join ', ')" }

# 4) 压缩
$zip = Join-Path $dist 'Image-Upscale-win64.zip'
Compress-Archive -Path $pkg -DestinationPath $zip
Write-Output "packaged: $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"
