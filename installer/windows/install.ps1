# HUCViewS インストーラー（Windows 10/11・管理者権限は不要）— 画面つき
# 3D Slicer（公式・無料）と HUCViewS 本体、AI（TotalSegmentator）を %LOCALAPPDATA%\HUCViewS に入れ、
# デスクトップとスタートメニューにアイコンを作り、「アプリと機能」からアンインストールできるようにする。
# 以後、起動のたびに GitHub から新しい版を自動で取り込む。患者データはどこにも送らない。
$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$Repo = 'lfb15345-del/HUCViewS'
$Manifest = "https://github.com/$Repo/releases/latest/download/latest.json"
$HV = Join-Path $env:LOCALAPPDATA 'HUCViewS'
$UA = 'HUCViewS-installer'

# ---------------- 画面
$f = New-Object Windows.Forms.Form
$f.Text = 'HUCViewS のインストール'; $f.ClientSize = New-Object Drawing.Size(580, 310)
$f.FormBorderStyle = 'FixedDialog'; $f.MaximizeBox = $false; $f.StartPosition = 'CenterScreen'; $f.BackColor = [Drawing.Color]::White
$font = 'Yu Gothic UI'
function L($text, $x, $y, $w, $h, $size, $bold, $color) {
  $l = New-Object Windows.Forms.Label; $l.Text = $text; $l.Location = New-Object Drawing.Point($x, $y); $l.Size = New-Object Drawing.Size($w, $h)
  $st = if ($bold) { [Drawing.FontStyle]::Bold } else { [Drawing.FontStyle]::Regular }
  $l.Font = New-Object Drawing.Font($font, $size, $st); if ($color) { $l.ForeColor = $color }; $f.Controls.Add($l); $l
}
$null = L 'HUCViewS　心臓・大動脈 3D ビューア' 24 18 520 34 15 $true ([Drawing.Color]::FromArgb(40, 70, 130))
$null = L '研究・教育用です（医療機器ではありません）。全部で 10〜30 分ほどかかります。この間も PC は普通に使えます。' 26 58 510 40 9.5 $false ([Drawing.Color]::DimGray)
$step = L '準備しています…' 26 108 510 26 11 $true $null
$bar = New-Object Windows.Forms.ProgressBar; $bar.Location = New-Object Drawing.Point(26, 140); $bar.Size = New-Object Drawing.Size(508, 22); $bar.Maximum = 1000; $f.Controls.Add($bar)
$detail = L '' 26 168 530 60 9 $false ([Drawing.Color]::Gray)
$btnRun = New-Object Windows.Forms.Button; $btnRun.Text = 'HUCViewS を起動'; $btnRun.Location = New-Object Drawing.Point(306, 258); $btnRun.Size = New-Object Drawing.Size(140, 34); $btnRun.Visible = $false; $f.Controls.Add($btnRun)
$btnClose = New-Object Windows.Forms.Button; $btnClose.Text = '閉じる'; $btnClose.Location = New-Object Drawing.Point(456, 258); $btnClose.Size = New-Object Drawing.Size(98, 34); $btnClose.Visible = $false; $f.Controls.Add($btnClose)
$script:closed = $false
$btnClose.Add_Click({ $f.Close() }); $f.Add_FormClosed({ $script:closed = $true })
$btnRun.Add_Click({ Start-Process -FilePath (Join-Path $HV 'HeartView.bat') -WorkingDirectory $HV -WindowStyle Hidden; $f.Close() })
$f.Show(); [Windows.Forms.Application]::DoEvents()

function Pump { [Windows.Forms.Application]::DoEvents(); if ($script:closed) { throw 'キャンセルされました' } }
function Wait-Ms($ms) { $t = [DateTime]::Now.AddMilliseconds($ms); while ([DateTime]::Now -lt $t) { Pump; Start-Sleep -Milliseconds 50 } }
function Step($p0, $text, $sub) { $step.Text = $text; $detail.Text = $sub; $bar.Value = [Math]::Min(1000, [int]($p0 * 10)); Pump }
function Prog($p) { $bar.Value = [Math]::Max($bar.Value, [Math]::Min(1000, [int]($p * 10))); Pump }
function Download($url, $out, $p0, $p1, $total) {
  $wc = New-Object Net.WebClient; $wc.Headers.Add('User-Agent', $UA)
  $task = $wc.DownloadFileTaskAsync([Uri]$url, $out)
  while (-not $task.IsCompleted) {
    if ($total -gt 0 -and (Test-Path $out)) {
      $n = (Get-Item $out).Length; Prog ($p0 + ($p1 - $p0) * [Math]::Min(1.0, $n / $total))
      $detail.Text = ('{0:N0} / {1:N0} MB' -f ($n / 1MB), ($total / 1MB))
    }
    Wait-Ms 150
  }
  if ($task.IsFaulted) { throw $task.Exception.InnerException }
  Prog $p1
}
function Wait-Proc($p, $p0, $p1, $expectSec) {
  $start = [DateTime]::Now
  while (-not $p.HasExited) { $s = ([DateTime]::Now - $start).TotalSeconds; Prog ($p0 + ($p1 - $p0) * [Math]::Min(0.97, $s / $expectSec)); Wait-Ms 300 }
  Prog $p1
}
function Run-Slicer($phase, $hidden, $p0, $p1, $expectSec) {
  $env:HEARTVIEW_HOME = Join-Path $HV 'app'; $env:HUCVIEWS_SETUP_PHASE = $phase
  $a = @('--no-splash'); if ($hidden) { $a += '--no-main-window' }; $a += @('--python-script', ('"' + (Join-Path $HV 'app\setup_in_slicer.py') + '"'))
  $p = Start-Process -FilePath (Join-Path $HV 'Slicer\Slicer.exe') -ArgumentList $a -PassThru
  Wait-Proc $p $p0 $p1 $expectSec
  Remove-Item Env:HUCVIEWS_SETUP_PHASE -ErrorAction SilentlyContinue
}

try {
  New-Item -ItemType Directory -Force -Path $HV | Out-Null
  $slicer = Join-Path $HV 'Slicer\Slicer.exe'
  if (-not (Test-Path $slicer)) {
    Step 2 '3D Slicer（公式・無料）をダウンロードしています…' ''
    $info = Invoke-RestMethod -Uri 'https://download.slicer.org/find?os=win&stability=release' -UserAgent $UA
    $exe = Join-Path $env:TEMP 'HUCViewS_SlicerSetup.exe'
    Download ('https://download.slicer.org' + $info.download_url) $exe 2 40 ([double]$info.size)
    Step 40 '3D Slicer を入れています…' '数分かかります'
    $p = Start-Process -FilePath $exe -ArgumentList @('/S', ('/D=' + (Join-Path $HV 'Slicer'))) -PassThru
    Wait-Proc $p 40 55 150
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $slicer)) { throw '3D Slicer を入れられませんでした。' }
  }
  Step 55 'HUCViewS 本体を取得しています…' ''
  $man = Invoke-RestMethod -Uri $Manifest -UserAgent $UA
  $zip = Join-Path $env:TEMP 'HUCViewS-app.zip'
  Download $man.app_zip $zip 55 58 0
  if ($man.sha256 -and ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne ([string]$man.sha256).ToLower())) { throw 'ダウンロードしたファイルが壊れています。もう一度実行してください。' }
  Expand-Archive -Path $zip -DestinationPath $HV -Force
  Remove-Item $zip -Force -ErrorAction SilentlyContinue
  Set-Content -Path (Join-Path $HV 'update_source.txt') -Value $Manifest -Encoding UTF8
  Copy-Item (Join-Path $HV 'app\HeartView.bat') (Join-Path $HV 'HeartView.bat') -Force

  Step 58 'AI（TotalSegmentator）の機能を入れています…' '数分かかります'
  Run-Slicer 'ext' $true 58 66 90
  Step 66 'AI の部品（PyTorch など・約2GB）を入れています…' '10〜20 分かかります。途中で 3D Slicer の画面が出ても、そのままお待ちください。'
  Run-Slicer 'py' $false 66 96 600

  Step 96 'アイコンを作っています…' ''
  $p = Start-Process powershell -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', ('"' + (Join-Path $HV 'app\make_shortcut.ps1') + '"')) -WindowStyle Hidden -PassThru
  Wait-Proc $p 96 99 10
  # 「設定 → アプリ」からアンインストールできるように（この PC のこのユーザーだけ）
  $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HUCViewS'
  New-Item -Path $key -Force | Out-Null
  $sizeKB = [int]((Get-ChildItem $HV -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1KB)
  $vals = @{ DisplayName = 'HUCViewS（心臓・大動脈 3D ビューア）'; DisplayVersion = [string]$man.version; Publisher = 'HUCVS, Hokkaido University';
             DisplayIcon = (Join-Path $HV 'app\HUCViewS.ico'); InstallLocation = $HV; URLInfoAbout = "https://github.com/$Repo";
             UninstallString = ('powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $HV 'app\uninstall.ps1') + '"') }
  foreach ($k in $vals.Keys) { New-ItemProperty -Path $key -Name $k -Value $vals[$k] -PropertyType String -Force | Out-Null }
  foreach ($k in @('NoModify', 'NoRepair')) { New-ItemProperty -Path $key -Name $k -Value 1 -PropertyType DWord -Force | Out-Null }
  New-ItemProperty -Path $key -Name 'EstimatedSize' -Value $sizeKB -PropertyType DWord -Force | Out-Null

  $bar.Value = 1000
  $step.Text = 'インストールが終わりました'; $step.ForeColor = [Drawing.Color]::FromArgb(30, 130, 60)
  $detail.Text = "デスクトップとスタートメニューの「HUCViewS」から起動できます。`n心腔の色分けを使うときは、起動後の画面で「AI ライセンスを登録する」から番号を入れてください（無料）。"
  $btnRun.Visible = $true; $btnClose.Visible = $true
} catch {
  if (-not $script:closed) {
    $step.Text = 'うまくいきませんでした'; $step.ForeColor = [Drawing.Color]::Firebrick
    $detail.Text = ('理由: ' + $_.Exception.Message + "`nネットにつながっているか確認して、もう一度このインストーラーを実行してください。")
    $btnClose.Visible = $true
  }
}
while (-not $script:closed) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 50 }
