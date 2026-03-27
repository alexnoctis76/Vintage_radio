@echo off
REM Build script for Vintage Radio application on Windows
REM Usage: build_windows.bat [--no-clean]
REM
REM Prerequisites:
REM   - Python 3.8+ with venv
REM   - PyInstaller: pip install pyinstaller
REM
REM Output: dist\Vintage Radio\ (app folder with vintage_radio.exe)

setlocal enabledelayedexpansion

set SCRIPT_DIR=%~dp0
for %%i in ("%SCRIPT_DIR%..") do set PROJECT_ROOT=%%~fi
set APP_NAME=Vintage Radio
set BUILD_DIR=%PROJECT_ROOT%\dist
set SPEC_FILE=%SCRIPT_DIR%vintage_radio.spec
set EXE_PATH=%BUILD_DIR%\Vintage Radio\Vintage Radio.exe

echo.
echo ==========================================
echo Vintage Radio Windows Build Script
echo ==========================================
echo App Name: %APP_NAME%
echo Build Directory: %BUILD_DIR%
echo ==========================================
echo.

REM Check for PyInstaller
where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo Error: PyInstaller not found. Install with: pip install pyinstaller
    exit /b 1
)

REM Parse command-line arguments
set CLEAN=true
:parse_args
if "%~1"=="" goto done_parsing
if "%~1"=="--no-clean" (
    set CLEAN=false
    shift
    goto parse_args
)
shift
goto parse_args

:done_parsing

REM Force-stop Vintage Radio (process tree + retries) so dist\Vintage Radio can be deleted
echo Force-stopping Vintage Radio (unlocks dist folder^)...
python "%SCRIPT_DIR%kill_vintage_radio_build_locks.py"
if errorlevel 1 (
    echo Warning: kill helper failed; trying taskkill /T anyway...
    taskkill /IM "Vintage Radio.exe" /F /T >nul 2>&1
)

REM Clean previous build
if "%CLEAN%"=="true" (
    echo Cleaning previous build...
    if exist "%BUILD_DIR%" (
        rmdir /s /q "%BUILD_DIR%"
    )
    mkdir "%BUILD_DIR%"
)

REM Run PyInstaller
echo Building application with PyInstaller...
pyinstaller "%SPEC_FILE%" --noconfirm --distpath "%BUILD_DIR%" --workpath "%PROJECT_ROOT%\build\pyinstaller_temp"

if not exist "%EXE_PATH%" (
    echo Error: Failed to build executable at %EXE_PATH%
    exit /b 1
)

echo.
echo ==========================================
echo Build Complete!
echo ==========================================
echo Executable: %EXE_PATH%
echo.
echo To run the app, double-click:
echo   %EXE_PATH%
echo ==========================================
echo.

