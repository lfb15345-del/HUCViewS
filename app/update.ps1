# HeartView 自動更新（NAS → この PC）。起動時と毎日の定時に実行される。
# ・app\version.txt が NAS と違えば、アプリ部分（app フォルダ）を入れ替える（数秒）
# ・full_version.txt が NAS と違えば、Slicer 本体・AI データを含めて丸ごと入れ替える（数分）
# ・ライセンス設定（totalseg\config.json）と update_source.txt は上書きしない
param([switch]$Quiet, [switch]$FromLauncher)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$log = Join-Path $root 'update_log.txt'
function Log($m) { $line = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $m; Add-Content -Path $log -Value $line -Encoding UTF8; if (-not $Quiet) { Write-Host $m } }
$srcFile = Join-Path $root 'update_source.txt'
if (-not (Test-Path $srcFile)) { exit 0 }
$nas = (Get-Content $srcFile -Raw -Encoding UTF8).Trim()
if (-not $nas) { exit 0 }
if ($nas -match '^https?://') { exit 0 }   # ネット（GitHub）から更新する版は、起動時に Python 側で更新する
if (-not (Test-Path $nas)) { Log "NAS に届きません（$nas）。今の版のまま。"; exit 0 }
$full = Join-Path $nas 'HeartView_full'
function ReadVer($p) { if (Test-Path $p) { (Get-Content $p -Raw).Trim() } else { '' } }

# 1) 丸ごと更新（Slicer や AI データが変わったとき）
$nv = ReadVer (Join-Path $full 'full_version.txt'); $cv = ReadVer (Join-Path $root 'full_version.txt')
if ($nv -and $nv -ne $cv) {
  $running = Get-Process SlicerApp-real -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$root*" }
  if ($running) { Log "ビューアが起動中なので丸ごと更新は次回に回します（$cv → $nv）" }
  else {
    Log "丸ごと更新します $cv → $nv（数分かかります）"
    $xf = @('config.json','update_source.txt','full_version.txt','update_log.txt'); if ($FromLauncher) { $xf += 'HeartView.bat' }
    robocopy $full $root /MIR /R:1 /W:1 /NFL /NDL /NP /NJH /XF $xf /XD __pycache__ | Out-Null
    if ($LASTEXITCODE -lt 8) { Copy-Item (Join-Path $full 'full_version.txt') (Join-Path $root 'full_version.txt') -Force; Log "丸ごと更新 完了" }
    else { Log "丸ごと更新に失敗（robocopy $LASTEXITCODE）。次回また試します" }
  }
}
# 2) アプリ部分だけの更新（普段の改良はこちら）
$na = ReadVer (Join-Path $nas 'app\version.txt'); $ca = ReadVer (Join-Path $root 'app\version.txt')
if ($na -and $na -ne $ca) {
  Log "アプリを更新します $ca → $na"
  robocopy (Join-Path $nas 'app') (Join-Path $root 'app') /MIR /R:1 /W:1 /NFL /NDL /NP /NJH /XD __pycache__ | Out-Null
  if ($LASTEXITCODE -lt 8) { Log "アプリ更新 完了" } else { Log "アプリ更新に失敗（robocopy $LASTEXITCODE）" }
  foreach ($f in @('README_はじめに.txt')) { $p = Join-Path $nas $f; if (Test-Path $p) { Copy-Item $p (Join-Path $root $f) -Force } }
}
exit 0
