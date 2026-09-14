# 下载/生成全部打包模型（幂等：已存在则跳过）
# 来源：
#   waifu2x 三模型  — nihui/waifu2x-ncnn-vulkan release（MIT）
#   realcugan pro/se — nihui/realcugan-ncnn-vulkan release（MIT）
#   digital-art-4x   — upscayl/upscayl resources（Upscayl 官方允许再分发）
#   general-x4v3     — xinntao/Real-ESRGAN v0.2.5.0 权重（BSD-3）经 pnnx 转换（需 torch+pnnx）
$ErrorActionPreference = 'Stop'

$repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$modelsDir = Join-Path $repo 'models'
$tmpDir = 'D:\tmp\image-upscale-setup'
New-Item -ItemType Directory -Force -Path $modelsDir, $tmpDir | Out-Null

function Get-ReleaseAsset($repo, $pattern) {
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest"
    $a = $rel.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1
    if (-not $a) { throw "no asset matching $pattern in $repo latest release" }
    $zipPath = Join-Path $tmpDir $a.name
    if (-not (Test-Path $zipPath)) {
        Write-Output "downloading $($a.browser_download_url)"
        Invoke-WebRequest -Uri $a.browser_download_url -OutFile $zipPath
    }
    return $zipPath
}

function Extract-Prefix($zipPath, $prefix, $destName) {
    $dest = Join-Path $modelsDir $destName
    if (Test-Path $dest) { Write-Output "skip (exists): $destName"; return }
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entries = $zip.Entries | Where-Object { $_.FullName -match $prefix -and $_.Name -ne '' }
        if (-not $entries) { throw "no entries matching $prefix in $zipPath" }
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        foreach ($e in $entries) {
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($e, (Join-Path $dest $e.Name), $true)
        }
    } finally { $zip.Dispose() }
    Write-Output "extracted: $destName"
}

# 1) waifu2x 系（waifu2x_upconv_7_art / waifu2x_cunet / waifu2x_upconv_7_photo；工单 30 改名）
$w2xZip = Get-ReleaseAsset 'nihui/waifu2x-ncnn-vulkan' 'windows\.zip$'
Extract-Prefix $w2xZip 'models-upconv_7_anime_style_art_rgb/' 'waifu2x_upconv_7_art'
Extract-Prefix $w2xZip 'models-cunet/' 'waifu2x_cunet'
Extract-Prefix $w2xZip 'models-upconv_7_photo/' 'waifu2x_upconv_7_photo'

# 2) Real-CUGAN pro/se
$cuganZip = Get-ReleaseAsset 'nihui/realcugan-ncnn-vulkan' 'windows\.zip$'
Extract-Prefix $cuganZip 'models-pro/' 'realcugan-pro'
Extract-Prefix $cuganZip 'models-se/' 'realcugan-se'

# 3) digital-art-4x（Upscayl 仓库直取）
$daDir = Join-Path $modelsDir 'digital-art-4x'
if (-not (Test-Path (Join-Path $daDir 'digital-art-4x.bin'))) {
    New-Item -ItemType Directory -Force -Path $daDir | Out-Null
    foreach ($ext in 'param', 'bin') {
        $url = "https://raw.githubusercontent.com/upscayl/upscayl/main/resources/models/digital-art-4x.$ext"
        Invoke-WebRequest -Uri $url -OutFile (Join-Path $daDir "digital-art-4x.$ext")
    }
    Write-Output "extracted: digital-art-4x"
} else { Write-Output "skip (exists): digital-art-4x" }

# 4) realesr-general-x4v3（需 python torch+pnnx）
$gv3 = Join-Path $modelsDir 'realesr-general-x4v3'
if (-not (Test-Path (Join-Path $gv3 'realesr-general-x4v3.bin'))) {
    Write-Output 'converting realesr-general-x4v3 via pnnx (torch required)...'
    python (Join-Path $PSScriptRoot 'convert-general-x4v3.py')
} else { Write-Output "skip (exists): realesr-general-x4v3" }

Write-Output 'all models ready'
