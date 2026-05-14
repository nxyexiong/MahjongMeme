@echo off
REM Build mahjong-meme.exe (single-file) into build\ via PyInstaller.
REM
REM Usage: build.cmd            -> normal build
REM        build.cmd clean       -> wipe build\ first
REM
REM Output: build\mahjong-meme.exe
REM Build artifacts (spec, work, dist intermediates) live under build\_work\.

setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "SRC=%ROOT%\src"
set "BUILD=%ROOT%\build"
set "VENV=%SRC%\.venv"
set "PY=%VENV%\Scripts\python.exe"
set "DATA_SCRIPTS=%SRC%\mahjong_meme\scripts"

if /I "%~1"=="clean" (
  if exist "%BUILD%" (
    echo [build] cleaning %BUILD%
    rmdir /s /q "%BUILD%"
  )
)

if not exist "%PY%" (
  echo [build] creating venv at %VENV%
  where python >nul 2>nul || (
    echo [build] ERROR: 'python' is not on PATH. Install Python 3.10+ and retry.
    exit /b 1
  )
  python -m venv "%VENV%" || goto :err
)

echo [build] upgrading pip
"%PY%" -m pip install --upgrade --quiet pip || goto :err

echo [build] installing project + pyinstaller
"%PY%" -m pip install --quiet pyinstaller || goto :err
"%PY%" -m pip install --quiet -e "%SRC%" || goto :err

if not exist "%BUILD%" mkdir "%BUILD%"

echo [build] running pyinstaller
"%PY%" -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --console ^
  --name mahjong-meme ^
  --collect-all playwright ^
  --collect-all mahjong_meme ^
  --add-data "%DATA_SCRIPTS%;mahjong_meme/scripts" ^
  --distpath "%BUILD%" ^
  --workpath "%BUILD%\_work" ^
  --specpath "%BUILD%\_work" ^
  "%SRC%\mahjong_meme\__main__.py" || goto :err

if not exist "%BUILD%\mahjong-meme.exe" (
  echo [build] ERROR: pyinstaller finished but mahjong-meme.exe is missing.
  exit /b 1
)

echo.
echo [build] OK: %BUILD%\mahjong-meme.exe
for %%I in ("%BUILD%\mahjong-meme.exe") do echo [build]     size: %%~zI bytes
exit /b 0

:err
echo [build] FAILED (exit %ERRORLEVEL%)
exit /b 1
