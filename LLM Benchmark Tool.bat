@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "APP_DIR=%PROJECT_DIR%llm-bench-app"

if not exist "%APP_DIR%\app.py" (
    echo Could not find the benchmark app at:
    echo "%APP_DIR%\app.py"
    echo.
    echo Keep this launcher in the LLM-Benchmark folder, next to the llm-bench-app folder.
    pause
    exit /b 1
)

cd /d "%APP_DIR%"

where python >nul 2>nul
if %errorlevel% equ 0 (
    python app.py
    set "APP_EXIT=%errorlevel%"
    if not "%APP_EXIT%"=="0" pause
    exit /b %APP_EXIT%
)

where py >nul 2>nul
if %errorlevel% equ 0 (
    py app.py
    set "APP_EXIT=%errorlevel%"
    if not "%APP_EXIT%"=="0" pause
    exit /b %APP_EXIT%
)

echo Python was not found on PATH.
echo Install Python, or add it to PATH, then run this launcher again.
pause
exit /b 1
