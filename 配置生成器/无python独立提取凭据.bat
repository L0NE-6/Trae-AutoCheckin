@echo off
chcp 65001 >nul
setlocal
title Trae credential extractor (no Python)

set "BATFILE=%~f0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$m='#PS'+'START'; $s=[IO.File]::ReadAllText($env:BATFILE); $i=$s.LastIndexOf($m); iex $s.Substring($i+$m.Length)"

echo.
pause
exit /b

#PSSTART
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$salt = [byte[]](77,212,194,230,184,49,98,9,14,82,179,199,166,115,59,164,28,178,70,43,130,154,181,138,25,107,57,219,87,23,117,36,244,155,175,127,8,232,214,141,38,167,46,55,193,169,90,47,31,5,165,24,146,174,242,148,151,50,182,42,56,170,221,88)

function Decrypt-B64([string]$b64) {
  $raw = [Convert]::FromBase64String($b64.Trim())
  if ($raw.Length -le 38) { throw 'payload too short' }
  $rb = New-Object byte[] 32
  $encLen = $raw.Length - 38
  $enc = New-Object byte[] $encLen
  [Array]::Copy($raw, 6, $rb, 0, 32)
  [Array]::Copy($raw, 38, $enc, 0, $encLen)

  $sha = [Security.Cryptography.SHA512]::Create()
  $h1 = $sha.ComputeHash($rb)
  $mix = New-Object byte[] ($h1.Length + $salt.Length)
  [Array]::Copy($h1, 0, $mix, 0, $h1.Length)
  [Array]::Copy($salt, 0, $mix, $h1.Length, $salt.Length)
  $h2 = $sha.ComputeHash($mix)

  $aes = [Security.Cryptography.Aes]::Create()
  $aes.Mode = 'CBC'
  $aes.Padding = 'None'
  $aes.Key = $h2[0..15]
  $aes.IV = $h2[16..31]
  $dec = $aes.CreateDecryptor()
  $pt = $dec.TransformFinalBlock($enc, 0, $enc.Length)
  $dec.Dispose(); $aes.Dispose()

  if ($pt.Length -le 64) { return '' }
  $n = $pt.Length - 64
  $body = New-Object byte[] $n
  [Array]::Copy($pt, 64, $body, 0, $n)

  $pad = [int]$body[$n - 1]
  if ($pad -ge 1 -and $pad -le 16) {
    $n = $n - $pad
  } else {
    while ($n -gt 0 -and $body[$n - 1] -eq 0) { $n-- }
  }
  if ($n -le 0) { return '' }
  return [Text.Encoding]::UTF8.GetString($body, 0, $n)
}

$accKey = 'iCubeAuthInfo://icube.cloudide'
$devPrefix = 'iCubeAuthInfo://icube-dc:'
$names = @('Trae CN', 'TRAE SOLO CN', 'TRAE SOLO', 'Trae')
$candidates = @()
foreach ($n in $names) {
  $p = Join-Path $env:APPDATA ($n + '\User\globalStorage\storage.json')
  if (Test-Path $p) { $candidates += $p }
}

if ($candidates.Count -eq 0) {
  Write-Host '[ERROR] 没找到 storage.json。请先打开 Trae 客户端并登录一次。'
  exit 1
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('# Trae credential dump  ' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))
$lines.Add('')
$found = $false

foreach ($path in $candidates) {
  try { $obj = Get-Content -Raw -Encoding UTF8 $path | ConvertFrom-Json } catch { continue }

  $accEnc = $null
  foreach ($p in $obj.PSObject.Properties) {
    if ($p.Name -eq $accKey) { $accEnc = [string]$p.Value }
  }

  $deviceId = ''
  $devEnc = $null
  foreach ($p in $obj.PSObject.Properties) {
    if ($p.Name.StartsWith($devPrefix)) {
      $suffix = $p.Name.Substring($devPrefix.Length)
      if ($suffix -match '^\d{12,20}$') { $deviceId = $suffix; $devEnc = [string]$p.Value }
    } elseif ($p.Name -eq 'iCubeAuthInfo://icube-dc' -and ([string]$p.Value) -match '^\d{12,20}$') {
      $deviceId = [string]$p.Value
    }
  }

  if (-not $accEnc) { continue }
  try { $txt = Decrypt-B64 $accEnc } catch { continue }
  if (-not $txt) { continue }

  $rt = [regex]::Match($txt, '"refreshToken"\s*:\s*"([^"]+)"').Groups[1].Value
  $at = [regex]::Match($txt, '"token"\s*:\s*"([^"]+)"').Groups[1].Value
  $uid = [regex]::Match($txt, '"userId"\s*:\s*"(\d+)"').Groups[1].Value
  $nick = [regex]::Match($txt, '"username"\s*:\s*"([^"]*)"').Groups[1].Value
  if (-not $rt) { continue }

  if (-not $uid -and $at) {
    try {
      $seg = $at.Split('.')[1]
      $seg = $seg.Replace('-', '+').Replace('_', '/')
      while ($seg.Length % 4) { $seg += '=' }
      $j = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($seg)) | ConvertFrom-Json
      $uid = [string]$j.data.id
    } catch { }
  }
  $name = $nick
  if (-not $name) { $name = '用户' + $uid }

  $acc = [ordered]@{
    accessToken  = $at
    refreshToken = $rt
    uid          = $uid
    name         = $name
    realDeviceId = $deviceId
  }
  $json = ConvertTo-Json -InputObject @($acc) -Compress -Depth 5
  if (-not $json.StartsWith('[')) { $json = '[' + $json + ']' }

  $lines.Add('=' * 64)
  $lines.Add('TRAE_ACCOUNTS  (共 1 个账号，整行复制到环境变量)')
  $lines.Add('=' * 64)
  $lines.Add(('  1) {0}  UID {1}' -f $name, $uid))
  $lines.Add('-' * 64)
  $lines.Add($json)
  $lines.Add('=' * 64)
  $lines.Add('提示：换行会被 JSON 破坏，请整行复制（不要手动折行）。')

  $priv = ''
  $pub = ''
  if ($devEnc) {
    try {
      $dev = Decrypt-B64 $devEnc | ConvertFrom-Json
      $priv = [string]$dev.privateKeyPEM
      $pub = [string]$dev.publicKeyPEM
    } catch { }
  }
  $mid = [string]$obj.'telemetry.machineId'

  $lines.Add('=' * 64)
  $lines.Add(('设备密钥（来源: {0}）' -f $path))
  $lines.Add('=' * 64)
  $lines.Add('TRAE_DEVICE_ID=' + $deviceId)
  $lines.Add('TRAE_MACHINE_ID=' + $mid)
  $lines.Add('')
  if ($priv) {
    $lines.Add('TRAE_DEVICE_KEY_PEM=' + $priv.Trim().Replace("`r`n", '\n').Replace("`n", '\n'))
    $lines.Add('')
    $lines.Add('TRAE_DEVICE_PUB_PEM=' + $pub.Trim().Replace("`r`n", '\n').Replace("`n", '\n'))
    $lines.Add('=' * 64)
    $lines.Add('提示：PEM 里的换行已写成 \n，直接整行复制即可。')
  } else {
    $lines.Add('[!] 没找到设备私钥，跳过 TRAE_DEVICE_KEY_PEM')
  }
  $found = $true
  break
}

if (-not $found) {
  Write-Host '[ERROR] 已找到 storage.json，但里面没有可解密的登录凭据。'
  Write-Host '        请在 Trae 客户端登录后重试。'
  exit 1
}

$lines | ForEach-Object { Write-Host $_ }
Write-Host ''

if (-not [Environment]::UserInteractive) {
  exit 0
}

Write-Host '凭据已在上方完整显示，可直接从终端复制。'
Write-Host '是否需要额外导出？'
Write-Host '  [1] 保存到文件（脚本同目录 trae-credentials.txt）'
Write-Host '  [2] 复制到剪贴板'
Write-Host '  [3] 不保存，直接退出（默认，直接回车即可）'
$choice = Read-Host '请输入 1/2/3 后回车'
Write-Host ''

if ($choice -eq '1') {
  $out = Join-Path (Split-Path -Parent $env:BATFILE) 'trae-credentials.txt'
  $confirm = Read-Host ('确认写入 ' + $out + ' ? [Y/N]')
  if ($confirm -match '^[Yy]') {
    $enc = New-Object Text.UTF8Encoding $false
    [IO.File]::WriteAllLines($out, $lines, $enc)
    Write-Host ('已保存到: ' + $out)
    Write-Host '[!] 此文件含密码级凭据，请勿泄露，用完请删除'
  } else {
    Write-Host '已取消保存，未写入任何文件。'
  }
} elseif ($choice -eq '2') {
  Set-Clipboard -Value ($lines -join "`r`n")
  Write-Host '已复制到剪贴板。提示：剪贴板可被其他程序读取，用完建议复制任意内容覆盖。'
} else {
  Write-Host '未保存任何文件。'
}
