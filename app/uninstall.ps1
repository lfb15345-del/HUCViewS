# HUCViewS のアンインストール（設定 → アプリ から呼ばれる）
Add-Type -AssemblyName System.Windows.Forms
$HV = Join-Path $env:LOCALAPPDATA 'HUCViewS'
$r = [Windows.Forms.MessageBox]::Show("HUCViewS（3D Slicer と AI の部品を含む）をこの PC から削除します。`n保存した症例（ドキュメント\HeartView症例）は消しません。`n`nよろしいですか？", 'HUCViewS のアンインストール', 'OKCancel', 'Question')
if ($r -ne 'OK') { exit 0 }
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.ExecutablePath -like "$HV\*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
foreach ($p in @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('Programs')) ''))) { $l = Join-Path $p 'HUCViewS.lnk'; if (Test-Path $l) { Remove-Item $l -Force } }
Unregister-ScheduledTask -TaskName 'HeartView_AutoUpdate' -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\HUCViewS' -Recurse -Force -ErrorAction SilentlyContinue
# 自分自身がフォルダの中にあるので、少し待ってから別のプロセスで消す
Start-Process cmd.exe -ArgumentList @('/c', 'timeout /t 3 /nobreak >nul & rmdir /s /q "' + $HV + '"') -WindowStyle Hidden
[Windows.Forms.MessageBox]::Show('HUCViewS を削除しました。', 'HUCViewS') | Out-Null
