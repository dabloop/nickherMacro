@echo off
title Nickher Macro - Build EXE
color 0A

echo.
echo  =============================================
echo   Nickher Macro - EXE Builder
echo  =============================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

:: Install / upgrade pip dependencies
echo  [1/3] Installing dependencies...
pip install pyinstaller pynput PySide6 --quiet
if errorlevel 1 (
    echo  [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo        Done.
echo.

:: Clean previous build artifacts.
:: NOTE: never delete *.spec here. NickherMacro.spec is hand-tuned and is what
:: keeps the build ~49 MB instead of ~250 MB. It is source, not build output.
echo  [2/3] Cleaning old build files...
if exist "build" rmdir /s /q "build"
if exist "dist"  rmdir /s /q "dist"
echo        Done.
echo.

:: Build from the spec. Do NOT pass --collect-all=PySide6 on the command line:
:: it bundles Qt WebEngine (an entire Chromium, ~200 MB) that this app never uses.
echo  [3/3] Building EXE (this may take a minute)...
echo.

pyinstaller --noconfirm --clean NickherMacro.spec

if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed. See output above for details.
    pause
    exit /b 1
)

echo.
echo  =============================================
echo   Build complete!
echo   Your EXE is at:  dist\NickherMacro.exe
for %%A in ("dist\NickherMacro.exe") do echo   Size: %%~zA bytes
echo  =============================================
echo.

:: Open the dist folder automatically
explorer dist

pause
