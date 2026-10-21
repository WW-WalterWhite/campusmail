@echo off
REM Starts CampusMail and opens it in your browser.
cd /d "%~dp0"
call .venv\Scripts\activate.bat || (echo Run setup.bat first. & pause & exit /b 1)
streamlit run app.py --browser.gatherUsageStats false
