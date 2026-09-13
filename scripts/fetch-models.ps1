# 下载 waifu2x-ncnn-vulkan release 并抽取首个打包模型
# 幂等：models/upconv_7_anime_style_art_rgb 已存在则跳过
$ErrorActionPreference = 'Stop'

$setupDir = 'D:\tmp\image-upscale-setup'
$modelsDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\models'))
$target = Join-Path $modelsDir 'upconv_7_anime_style_art_rgb'

New-Item -ItemType Directory -Force -Path $modelsDir | Out-Null

if (Test-Path $target) {
    Write-Output "model already present: $target"
    exit 0
}

# 查询最新 release 的 windows zip 资产
$rel = Invoke-RestMethod -Uri 'https://api.github.com/repos/nihui/waifu2x-ncnn-vulkan/releases/latest'
$asset = $rel.assets | Where-Object { $_.name -match 'windows\.zip$' } | Select-Object -First 1
if (-not $asset) { throw 'no windows.zip asset found in latest release' }

$zipPath = Join-Path $setupDir $asset.name
Write-Output "downloading $($asset.browser_download_url)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

Write-Output "extracting models-upconv_7_anime_style_art_rgb"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $entries = $zip.Entries | Where-Object { $_.FullName -match 'models-upconv_7_anime_style_art_rgb/' -and $_.Name -ne '' }
    if (-not $entries) { throw 'model entries not found in zip' }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    foreach ($e in $entries) {
        $dest = Join-Path $target $e.Name
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, $dest, $true)
    }
} finally {
    $zip.Dispose()
}

Write-Output "model ready: $target"
Write-Output "note: temp zip kept at $zipPath (manual cleanup allowed)"
