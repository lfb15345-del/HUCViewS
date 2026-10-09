# 心腔の詳細AI（heartchambers_highres）のライセンス番号を、この持ち運び版に登録する
$hv = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$cfgDir = Join-Path $hv 'totalseg'
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
$cfgPath = Join-Path $cfgDir 'config.json'
$lic = Read-Host 'ライセンス番号を入力してください（例: aca_XXXXXXXXXX）'
if (-not $lic) { Write-Host '中止しました'; exit 1 }
$cfg = [ordered]@{}
if (Test-Path $cfgPath) {
  $old = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($p in $old.PSObject.Properties) { $cfg[$p.Name] = $p.Value }
}
$cfg['license_number'] = $lic.Trim()
$cfg['send_usage_stats'] = $false
$cfg['statistics_disclaimer_shown'] = $true
$json = New-Object PSObject -Property $cfg | ConvertTo-Json
[System.IO.File]::WriteAllText($cfgPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host '登録しました。心臓3Dビューアを開き直してください。'
