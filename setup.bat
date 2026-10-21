@echo off
REM CampusMail one-time setup for Windows. Double-click this file.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m venv .venv || goto :error
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :error
where ollama >nul 2>nul
if errorlevel 1 (
  echo.
  echo Ollama is not installed. Get it from https://ollama.com/download then run setup.bat again.
  echo You can still use CampusMail in "Rules only" mode without it.
) else (
  echo Downloading the Qwen3 4B model ^(about 2.5 GB, first time only^)...
  ollama pull qwen3:4b
)
echo.
echo Setup finished. Double-click run.bat to start CampusMail.
pause
exit /b 0
:error
echo Setup failed. Check that Python 3.10 or newer is installed from https://www.python.org/downloads/
pause
exit /b 1
