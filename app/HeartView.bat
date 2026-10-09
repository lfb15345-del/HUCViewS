@echo off
setlocal
rem ===== HeartView launcher =====
set "HV=%~dp0"
set "HEARTVIEW_HOME=%HV%app"
if exist "%HV%totalseg\nnunet" set "TOTALSEG_HOME_DIR=%HV%totalseg"

if exist "%HV%app\update.ps1" powershell -NoProfile -ExecutionPolicy Bypass -File "%HV%app\update.ps1" -FromLauncher
set "SLICER="
if exist "%HV%Slicer\Slicer.exe" set "SLICER=%HV%Slicer\Slicer.exe"
if not defined SLICER for /d %%D in ("%LOCALAPPDATA%\slicer.org\*Slicer*") do if exist "%%D\Slicer.exe" set "SLICER=%%D\Slicer.exe"
if not defined SLICER for /d %%D in ("%ProgramFiles%\*Slicer*") do if exist "%%D\Slicer.exe" set "SLICER=%%D\Slicer.exe"
if not defined SLICER (
  echo 3D Slicer was not found. Please read README.
  pause
  exit /b 1
)
start "" "%SLICER%" --no-splash --python-script "%HV%app\heartview_start.py"
