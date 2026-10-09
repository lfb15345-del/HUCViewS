# HUCViewS インストーラー（Windows 10/11・管理者権限は不要）
# 3D Slicer（公式・無料）と HUCViewS 本体、AI（TotalSegmentator）を %LOCALAPPDATA%\HUCViewS に入れ、デスクトップにアイコンを作る。
# 以後、起動のたびに GitHub から新しい版を自動で取り込む。患者データはどこにも送らない。
$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
$Repo = 'lfb15345-del/HUCViewS'
$Manifest = "https://github.com/$Repo/releases/latest/download/latest.json"
$HV = Join-Path $env:LOCALAPPDATA 'HUCViewS'
function Step($m) { Write-Host ''; Write-Host ('■ ' + $m) -ForegroundColor Cyan }
function Get-File($url, $out) { $old = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'; try { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing } finally { $ProgressPreference = $old } }
function Run-Slicer($phase, [switch]$Hidden) {
  $env:HEARTVIEW_HOME = Join-Path $HV 'app'; $env:HUCVIEWS_SETUP_PHASE = $phase
  $a = @('--no-splash'); if ($Hidden) { $a += '--no-main-window' }; $a += @('--python-script', (Join-Path $HV 'app\setup_in_slicer.py'))
  $p = Start-Process -FilePath $script:slicer -ArgumentList $a -Wait -PassThru
  Remove-Item Env:HUCVIEWS_SETUP_PHASE -ErrorAction SilentlyContinue
  return $p.ExitCode
}
try {
  Write-Host 'HUCViewS（心臓・大動脈 3D ビューア）をインストールします。' -ForegroundColor Green
  Write-Host '研究・教育用です（医療機器ではありません）。全部で 10〜30 分ほどかかります（ネットの速さによる）。'
  New-Item -ItemType Directory -Force -Path $HV | Out-Null
  $script:slicer = Join-Path $HV 'Slicer\Slicer.exe'
  if (-not (Test-Path $script:slicer)) {
    Step '3D Slicer（公式・無料・約270MB）をダウンロードしています…'
    $exe = Join-Path $env:TEMP 'HUCViewS_SlicerSetup.exe'
    Get-File 'https://download.slicer.org/download?os=win&stability=release' $exe
    Step '3D Slicer を入れています（数分）…'
    Start-Process -FilePath $exe -ArgumentList @('/S', ('/D=' + (Join-Path $HV 'Slicer'))) -Wait
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $script:slicer)) { throw '3D Slicer を入れられませんでした。' }
  } else { Step '3D Slicer は入っています' }

  Step 'HUCViewS 本体を取得しています…'
  $man = Invoke-RestMethod -Uri $Manifest -UseBasicParsing
  $zip = Join-Path $env:TEMP 'HUCViewS-app.zip'
  Get-File $man.app_zip $zip
  if ($man.sha256 -and ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne ([string]$man.sha256).ToLower())) { throw 'ダウンロードしたファイルが壊れています。もう一度実行してください。' }
  Expand-Archive -Path $zip -DestinationPath $HV -Force
  Remove-Item $zip -Force -ErrorAction SilentlyContinue
  Set-Content -Path (Join-Path $HV 'update_source.txt') -Value $Manifest -Encoding UTF8
  Copy-Item (Join-Path $HV 'app\HeartView.bat') (Join-Path $HV 'HeartView.bat') -Force
  Write-Host ('  版: ' + $man.version)

  Step 'AI（TotalSegmentator）の拡張機能を入れています（数分）…'
  [void](Run-Slicer 'ext' -Hidden)
  Step 'AI の部品（PyTorch など・約2GB）を入れています。Slicer の画面が出たら、閉じるまでそのままお待ちください（10〜20分）…'
  [void](Run-Slicer 'py')

  Step 'デスクトップにアイコンを作っています…'
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $HV 'app\make_shortcut.ps1')
  Write-Host ''
  Write-Host 'インストールが終わりました。デスクトップの「HUCViewS」から起動してください。' -ForegroundColor Green
  Write-Host '（心腔の色分けを使うには、起動後の画面で「AI ライセンスを登録する」から無料の学術ライセンス番号を入れてください）'
  Write-Host ('記録: ' + (Join-Path $HV 'setup_log.txt'))
} catch {
  Write-Host ''
  Write-Host ('エラー: ' + $_.Exception.Message) -ForegroundColor Red
  Write-Host 'ネットにつながっているか確認して、もう一度実行してください。解決しないときは、このウィンドウの画面を作者に送ってください。'
}
Read-Host 'Enter キーで閉じます'
