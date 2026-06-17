@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "%~dp0run_vintage_radio.py" %*
) else (
  python "%~dp0run_vintage_radio.py" %*
)
exit /b %ERRORLEVEL%
