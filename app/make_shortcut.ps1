# デスクトップに「心臓3Dビューア」を作り、毎日の自動更新を登録する（管理者権限は不要）
$hv = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$desk = [Environment]::GetFolderPath('Desktop')
$w = New-Object -ComObject WScript.Shell
$old = Join-Path $desk '心臓3Dビューア.lnk'; if (Test-Path $old) { Remove-Item $old -Force }
$s = $w.CreateShortcut((Join-Path $desk 'HUCViewS.lnk'))
$s.TargetPath = (Join-Path $hv 'HeartView.bat')
$s.WorkingDirectory = $hv
$ico = Join-Path $hv 'app\HUCViewS.ico'
if (Test-Path $ico) { $s.IconLocation = "$ico,0" }
$s.Description = 'HUCViewS 心臓3Dビューア（研究・教育用）'
$s.WindowStyle = 7
$s.Save()
Write-Host 'デスクトップに「HUCViewS」を作りました。'
try {                                                   # スタートメニューにも
  $sm = $w.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) 'HUCViewS.lnk'))
  $sm.TargetPath = $s.TargetPath; $sm.WorkingDirectory = $hv; $sm.IconLocation = $s.IconLocation; $sm.Description = $s.Description; $sm.WindowStyle = 7; $sm.Save()
} catch {}
$srcTxt = Join-Path $hv 'update_source.txt'; $src = if (Test-Path $srcTxt) { (Get-Content $srcTxt -Raw -Encoding UTF8).Trim() } else { '' }
if ($src -match '^https?://') { Write-Host '更新はインターネット（GitHub）から起動時に自動で行います。'; exit 0 }
try {
  $ps = Join-Path $hv 'app\update.ps1'
  $act = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ps`" -Quiet"
  $trg = @((New-ScheduledTaskTrigger -Daily -At 7:30), (New-ScheduledTaskTrigger -Daily -At 12:30))
  $set = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
  Register-ScheduledTask -TaskName 'HeartView_AutoUpdate' -Action $act -Trigger $trg -Settings $set -Description 'HeartView: NAS から自動更新' -Force | Out-Null
  Write-Host '毎日 7:30 と 12:30 に NAS から自動更新するよう登録しました（PC が切れていたら次に起動したとき）。'
} catch { Write-Host ('自動更新の登録に失敗しました（起動時の更新は動きます）: ' + $_.Exception.Message) }
