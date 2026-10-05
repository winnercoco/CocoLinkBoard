@echo off
cd /d "%~dp0"

echo.
echo ========================================
echo Updating links.xlsx
echo ========================================
echo.

cd ..
cd scripts
python master_to_links.py

if errorlevel 1 (
    echo.
    echo ERROR: Script failed.
    echo.
    pause
    exit /b 1
)

echo.
echo ========================================
echo Successfully updated links.xlsx
echo ========================================
echo.

pause