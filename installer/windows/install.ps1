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
function Wait-Task($t, $sec) {
  # 非同期の処理を、画面を止めずに待つ（終われば、すぐ戻る。前は 0.1 秒ごとに見ていて、届くたびに待たされ、病院の回線で毎秒 50 KB ほどに落ちた）。
  # $sec 秒たっても終わらなければ $false。処理が失敗した時は、その例外がそのまま出る
  $end = [DateTime]::Now.AddSeconds($sec)
  while (-not $t.Wait(100)) { Pump; if ([DateTime]::Now -gt $end) { return $false } }
  return $true
}
function Download-Resume($url, $out, $p0, $p1, $total) {
  # 大きなファイル（3D Slicer）: つながりが切れたら、取れた所の続きから取り直す。病院の回線では 5 分ほど（117 MB）で切れた例がある。
  # 続きの頼み方: ふつうは HTTP の Range。Range に応えないサーバー（3D Slicer の配布元の Girder は、Range を頼んでも初めから返す）には、
  # 行き先（リダイレクトの後）の URL に offset=（Girder の続きの指定）を付ける。返ってきた所が取れた所の続きでなければ、つながずに初めから取る（壊れたファイルを作らない）。
  # 切れたままでも、取れた所までのファイルは残すので、もう一度インストーラーを実行すると続きから取る。60 秒なにも届かなければ、つなぎ直す
  $have = [long]0
  if (Test-Path $out) { $have = (Get-Item $out).Length; if ($have -gt $total) { Remove-Item $out -Force; $have = [long]0 } }
  $tries = 0; $useOffset = $false; $noOffset = $false; $final = $null
  while ($have -lt $total -and $tries -lt 40) {
    $tries++; $req = $null; $resp = $null; $fs = $null; $again = $false
    try {
      $u = $url
      if ($have -gt 0 -and $useOffset -and $final) { $u = $final + $(if ($final.Contains('?')) { '&' } else { '?' }) + 'offset=' + $have }
      $req = [Net.HttpWebRequest]::Create($u); $req.UserAgent = $UA; $req.AllowAutoRedirect = $true; $req.KeepAlive = $false   # 毎回新しくつなぐ（止めたつながりを使い回して失敗しない）
      if ($have -gt 0) { $req.AddRange([long]$have) }
      $t = $req.GetResponseAsync()
      if (-not (Wait-Task $t 60)) { throw 'つながりません' }
      $resp = $t.GetAwaiter().GetResult(); $code = [int]$resp.StatusCode     # .Result は失敗しても PowerShell では空になる（例外にならない）ので、GetResult で受ける
      if (-not $useOffset) { $final = $resp.ResponseUri.AbsoluteUri }
      $from = [long]0; $cr = [string]$resp.Headers['Content-Range']
      if ($code -eq 206 -and $cr -match '^bytes (\d+)-') { $from = [long]$Matches[1] }
      if ($have -gt 0 -and -not ($code -eq 206 -and $from -eq $have)) {      # 返ってきたのが続きではない
        if ($from -eq 0 -and -not $useOffset -and -not $noOffset) { $useOffset = $true; $again = $true; throw 'Range に応えないサーバー' }   # 次は offset で（待たずに）
        if ($from -ne 0) { throw '思わぬ所から返ってきました' }
        $have = [long]0                                                      # 初めから返ってきた → 初めから書く
      }
      if ($have -gt 0) { $mode = [IO.FileMode]::Append } else { $mode = [IO.FileMode]::Create }
      $fs = New-Object IO.FileStream($out, $mode, [IO.FileAccess]::Write)
      $st = $resp.GetResponseStream(); $buf = New-Object byte[] 1048576; $shown = [DateTime]::MinValue
      while ($true) {
        $r = $st.ReadAsync($buf, 0, $buf.Length)
        if (-not (Wait-Task $r 60)) { throw '60 秒なにも届きません' }
        $n = $r.GetAwaiter().GetResult(); if ($n -le 0) { break }
        $fs.Write($buf, 0, $n); $have += $n
        if (([DateTime]::Now - $shown).TotalMilliseconds -ge 200) {          # 画面は 0.2 秒ごとに（届くたびに描くと遅くなる）
          $shown = [DateTime]::Now; Prog ($p0 + ($p1 - $p0) * [Math]::Min(1.0, $have / $total))
          $detail.Text = ('{0:N0} / {1:N0} MB' -f ($have / 1MB), ($total / 1MB)) + $(if ($tries -gt 1) { "（つなぎ直し $($tries - 1) 回）" } else { '' })
        }
      }
    } catch {
      if ($script:closed) { throw }
      $e = $_.Exception; while ($e.InnerException) { $e = $e.InnerException }
      $sc = 0; if ($e -is [Net.WebException] -and $e.Response) { $sc = [int]$e.Response.StatusCode }   # 止める前に読む（止めた後は読めない）
      if ($req) { try { $req.Abort() } catch {} }
      if ($again) { $tries--; continue }                                      # offset で、すぐ頼み直す（数えない）
      if ($useOffset -and $sc -ge 400 -and $sc -lt 500) { $useOffset = $false; $noOffset = $true; continue }   # offset が効かない → 前のやり方（初めから）に戻す
      if ($sc -ge 400 -and $sc -lt 500 -and $sc -ne 408 -and $sc -ne 429) { break }   # 404 など（取り直しても同じ）は、すぐやめる
      Wait-Ms 3000
    } finally {
      if ($fs) { $fs.Close() }; if ($resp) { $resp.Close() }
    }
  }
  $script:dlTries = $tries; $script:dlOffset = $useOffset
  if ((Test-Path $out) -and (Get-Item $out).Length -eq $total) { Prog $p1; return $true }
  return $false
}
function Wait-Proc($p, $p0, $p1, $expectSec) {
  $start = [DateTime]::Now
  while (-not $p.HasExited) { $s = ([DateTime]::Now - $start).TotalSeconds; Prog ($p0 + ($p1 - $p0) * [Math]::Min(0.97, $s / $expectSec)); Wait-Ms 300 }
  Prog $p1
}
function Find-Slicer($want) {
  # 動作を確かめた版（latest.json の slicer）を入れる。見つからない時だけ、その日の最新の版
  $find = 'https://download.slicer.org/find?os=win&stability=release'
  if ($want) {
    try {
      $i = Invoke-RestMethod -Uri ($find + '&version=' + [Uri]::EscapeDataString([string]$want)) -UserAgent $UA
      if ($i.download_url -and ((-not $i.version) -or ([string]$i.version -eq [string]$want))) { return $i }
    } catch {}
  }
  Invoke-RestMethod -Uri $find -UserAgent $UA
}
function Log-Lines { $lg = Join-Path $HV 'setup_log.txt'; if (Test-Path $lg) { @(Get-Content $lg -Encoding UTF8) } else { @() } }
function Run-Slicer($phase, $hidden, $p0, $p1, $expectSec) {
  # うまくいったかは、setup_in_slicer.py が setup_log.txt の最後に書く OK / NG で見る（この回に足された行だけ）
  $n0 = @(Log-Lines).Count
  $env:HEARTVIEW_HOME = Join-Path $HV 'app'; $env:HUCVIEWS_SETUP_PHASE = $phase
  $a = @('--no-splash'); if ($hidden) { $a += '--no-main-window' }; $a += @('--python-script', ('"' + (Join-Path $HV 'app\setup_in_slicer.py') + '"'))
  $p = Start-Process -FilePath (Join-Path $HV 'Slicer\Slicer.exe') -ArgumentList $a -PassThru
  Wait-Proc $p $p0 $p1 $expectSec
  Remove-Item Env:HUCVIEWS_SETUP_PHASE -ErrorAction SilentlyContinue
  $l = @(Log-Lines)
  for ($k = $l.Count - 1; $k -ge $n0; $k--) { if ($l[$k] -match ' (OK|NG)\s*$') { return ($Matches[1] -eq 'OK') } }
  return $false
}

try {
  New-Item -ItemType Directory -Force -Path $HV | Out-Null
  Step 1 '版の情報を確かめています…' ''
  $man = Invoke-RestMethod -Uri $Manifest -UserAgent $UA
  $slicer = Join-Path $HV 'Slicer\Slicer.exe'
  if (-not (Test-Path $slicer)) {
    Step 2 '3D Slicer（公式・無料）をダウンロードしています…' ''
    $info = Find-Slicer $man.slicer
    $tag = ([string]$info.version -replace '[^0-9A-Za-z.\-]', ''); if (-not $tag) { $tag = [string]$info.size }
    $exe = Join-Path $env:TEMP ('HUCViewS_SlicerSetup_' + $tag + '.exe')                  # 版ごとの名前（切れた残りに、別の版の続きをつながない）
    $url = 'https://download.slicer.org' + $info.download_url
    if ([long]$info.size -gt 0) {
      if (-not (Download-Resume $url $exe 2 40 ([long]$info.size))) {               # 切れても、取れた所までは残す（次に実行すると続きから）
        throw '3D Slicer のダウンロードが何度も途中で切れました。取れた所までは残してあるので、もう一度実行すると続きから取ります。' }
    } else { Download $url $exe 2 40 0 }
    if ($info.sha512 -and ((Get-FileHash $exe -Algorithm SHA512).Hash.ToLower() -ne ([string]$info.sha512).ToLower())) {   # 続きをつないだ所も含めて、公式の値と同じか
      Remove-Item $exe -Force -ErrorAction SilentlyContinue; throw '3D Slicer のダウンロードが壊れていました。もう一度実行してください（初めから取り直します）。' }
    Step 40 '3D Slicer を入れています…' '数分かかります'
    $p = Start-Process -FilePath $exe -ArgumentList @('/S', ('/D=' + (Join-Path $HV 'Slicer'))) -PassThru
    Wait-Proc $p 40 55 150
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path $slicer)) { throw '3D Slicer を入れられませんでした。' }
  }
  Step 55 'HUCViewS 本体を取得しています…' ''
  $zip = Join-Path $env:TEMP 'HUCViewS-app.zip'
  Download $man.app_zip $zip 55 58 0
  if ($man.sha256 -and ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLower() -ne ([string]$man.sha256).ToLower())) { throw 'ダウンロードしたファイルが壊れています。もう一度実行してください。' }
  Expand-Archive -Path $zip -DestinationPath $HV -Force
  Remove-Item $zip -Force -ErrorAction SilentlyContinue
  Set-Content -Path (Join-Path $HV 'update_source.txt') -Value $Manifest -Encoding UTF8
  Copy-Item (Join-Path $HV 'app\HeartView.bat') (Join-Path $HV 'HeartView.bat') -Force

  Step 58 'AI（TotalSegmentator）と中心線（VMTK）の機能を入れています…' '数分かかります'
  $okExt = Run-Slicer 'ext' $true 58 66 90
  Step 66 'AI の部品（PyTorch など・約2GB）を入れています…' '10〜20 分かかります。途中で 3D Slicer の画面が出ても、そのままお待ちください。'
  $okPy = Run-Slicer 'py' $false 66 96 600

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
  if ($okExt -and $okPy) {
    $step.Text = 'インストールが終わりました'; $step.ForeColor = [Drawing.Color]::FromArgb(30, 130, 60)
    $detail.Text = "デスクトップとスタートメニューの「HUCViewS」から起動できます。`n心腔の色分けを使うときは、起動後の画面で「AI ライセンスを登録する」から番号を入れてください（無料）。"
  } else {
    $miss = if (-not $okExt) { 'AI（TotalSegmentator）の拡張機能' } else { 'AI の部品（PyTorch など）' }
    $step.Text = 'インストールは終わりましたが、AI が入っていません'; $step.ForeColor = [Drawing.Color]::DarkOrange
    $detail.Text = ($miss + 'が入りませんでした。表示・計測は使えます。' + "`nネットにつながっている所で、もう一度このインストーラーを実行すると入ります。`n記録: " + (Join-Path $HV 'setup_log.txt'))
  }
  $btnRun.Visible = $true; $btnClose.Visible = $true
} catch {
  if (-not $script:closed) {
    $step.Text = 'うまくいきませんでした'; $step.ForeColor = [Drawing.Color]::Firebrick
    $detail.Text = ('理由: ' + $_.Exception.Message + "`nネットにつながっているか確認して、もう一度このインストーラーを実行してください。")
    $btnClose.Visible = $true
  }
}
while (-not $script:closed) { [Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 50 }
