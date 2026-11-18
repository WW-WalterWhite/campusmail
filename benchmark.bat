@echo off
REM Measures CampusMail with the local model and saves a results table in the results folder.
REM Takes about 10-20 minutes on a laptop. Keep the Ollama app running.
cd /d "%~dp0"
call .venv\Scripts\activate.bat || (echo Run setup.bat first. & pause & exit /b 1)
python eval\benchmark.py %*
echo.
echo Send the newest results\benchmark_*.md file to your team (or paste it into the status sheet).
pause
