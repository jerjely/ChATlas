@echo off
setlocal EnableExtensions
title ChATlas installer
cd /d "%~dp0"
echo.
echo    =============================================
echo      ChATlas  -  retina connectome explorer
echo    =============================================
echo.

rem ---- find Miniconda / Anaconda ---------------------------------------------
set "CONDA_BAT="
for %%P in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\Miniconda3" "%LOCALAPPDATA%\miniconda3" "%ProgramData%\miniconda3" "%ProgramData%\Miniconda3" "%USERPROFILE%\anaconda3" "%ProgramData%\Anaconda3") do (
    if not defined CONDA_BAT if exist "%%~P\condabin\conda.bat" set "CONDA_BAT=%%~P\condabin\conda.bat"
)
if not defined CONDA_BAT for /f "delims=" %%C in ('where conda.bat 2^>nul') do if not defined CONDA_BAT set "CONDA_BAT=%%C"
if not defined CONDA_BAT (
    echo Miniconda was not found. Install it from https://docs.conda.io/en/latest/miniconda.html and run this again.
    pause
    exit /b 1
)
echo Using conda: %CONDA_BAT%
echo.

rem ---- create or update the "chatlas" environment ------------------------------
call "%CONDA_BAT%" env list | findstr /r /c:"^chatlas " >nul
if %errorlevel%==0 (
    echo Updating the existing "chatlas" environment...
    call "%CONDA_BAT%" env update -n chatlas -f environment.yml --prune
) else (
    echo Creating the "chatlas" environment - this takes a few minutes...
    call "%CONDA_BAT%" env create -n chatlas -f environment.yml
)
if errorlevel 1 goto :fail

call "%CONDA_BAT%" activate chatlas
if errorlevel 1 goto :fail
set "ENVDIR=%CONDA_PREFIX%"
echo Environment: %ENVDIR%

rem ---- install the app ------------------------------------------------------------
python -m pip install --no-deps --upgrade .
if errorlevel 1 goto :fail

rem ---- data folder, icon, launcher, shortcuts ----------------------------------
set "DATA=%USERPROFILE%\ChATlas"
if not exist "%DATA%" mkdir "%DATA%"
copy /y "chatlas\assets\chatlas.ico" "%DATA%\chatlas.ico" >nul
(
    echo @echo off
    echo start "" "%ENVDIR%\pythonw.exe" -m chatlas
) > "%DATA%\ChATlas.bat"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {" ^
  "  $s = $w.CreateShortcut((Join-Path $dir 'ChATlas.lnk'));" ^
  "  $s.TargetPath = '%ENVDIR%\pythonw.exe'; $s.Arguments = '-m chatlas';" ^
  "  $s.IconLocation = '%DATA%\chatlas.ico'; $s.WorkingDirectory = '%DATA%';" ^
  "  $s.Description = 'ChATlas - retina connectome explorer'; $s.Save() }"

echo.
echo    Done!  Start ChATlas from the desktop or Start-menu shortcut,
echo    or run  %DATA%\ChATlas.bat
echo.
echo    First time: open the Settings tab, paste your CAVE token and click "Save token".
echo    To reuse meshes you already downloaded, set the mesh cache folder there
echo    (e.g. %USERPROFILE%\mesh_cache).
echo.
pause
exit /b 0

:fail
echo.
echo Installation failed - see the messages above.
pause
exit /b 1
