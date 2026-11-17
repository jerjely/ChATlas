@echo off
setlocal
title ChATlas uninstaller
set "CONDA_BAT="
for %%P in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\Miniconda3" "%LOCALAPPDATA%\miniconda3" "%ProgramData%\miniconda3" "%USERPROFILE%\anaconda3" "%ProgramData%\Anaconda3") do (
    if not defined CONDA_BAT if exist "%%~P\condabin\conda.bat" set "CONDA_BAT=%%~P\condabin\conda.bat"
)
if not defined CONDA_BAT for /f "delims=" %%C in ('where conda.bat 2^>nul') do if not defined CONDA_BAT set "CONDA_BAT=%%C"
echo This removes the "chatlas" conda environment and the shortcuts.
echo Your data folder (%USERPROFILE%\ChATlas: settings, mesh cache, outputs) is kept.
pause
if defined CONDA_BAT call "%CONDA_BAT%" env remove -n chatlas -y
powershell -NoProfile -Command "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { Remove-Item (Join-Path $d 'ChATlas.lnk') -ErrorAction SilentlyContinue }"
del "%USERPROFILE%\ChATlas\ChATlas.bat" 2>nul
echo Removed.
pause
