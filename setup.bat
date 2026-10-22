@echo off
REM CampusMail one-time setup for Windows. Double-click this file.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo CampusMail needs Python 3.11 or newer.
  echo Install Python 3.12 or 3.13 from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
  echo then double-click setup.bat again.
  pause
  exit /b 1
)
%PY% -m venv .venv || goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :error
where ollama >nul 2>nul
if errorlevel 1 (
  echo.
  echo Ollama is not installed, or this window started before it was installed.
  echo Get it from https://ollama.com/download, then run setup.bat again.
  echo You can still use CampusMail in "Rules only" mode without it.
) else (
  echo Downloading the Qwen3 4B model ^(about 2.5 GB, first time only^)...
  ollama pull qwen3:4b
  if errorlevel 1 (
    echo.
    echo The model download failed. Check that the Ollama app is running and you are online,
    echo then run setup.bat again. CampusMail still works in "Rules only" mode.
  )
)
echo.
echo Setup finished. Double-click run.bat to start CampusMail.
pause
exit /b 0
:error
echo Setup failed while installing the Python packages. Check your internet connection and try again.
pause
exit /b 1
