@echo off
setlocal EnableDelayedExpansion
title LeadsOSINT - Setup & Launch
color 0A

echo.
echo  ============================================
echo    LeadsOSINT - Windows Setup ^& Launcher
echo  ============================================
echo.

rem -- Set install directory
set "INSTALL_DIR=%USERPROFILE%\LeadsOSINT"
set "APP_URL=http://localhost:5050"

rem -- Step 1: Check Python
echo [1/5] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  Python not found. Downloading Python 3.11...
    echo  Please wait - this only happens once.
    echo.
    curl -L -o "%TEMP%\python_installer.exe" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    if %errorlevel% neq 0 (
        echo.
        echo  ERROR: Could not download Python.
        echo  Please install Python manually from: https://python.org
        echo  Make sure to tick "Add Python to PATH" during install.
        pause
        exit /b 1
    )
    echo  Installing Python silently...
    "%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    del "%TEMP%\python_installer.exe" >nul 2>&1
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo  Python installed but PATH not refreshed.
        echo  Please CLOSE this window and run Setup.bat again.
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  Found: %%v

rem -- Step 2: Get LeadsOSINT files
echo.
echo [2/5] Getting LeadsOSINT files...
if exist "%INSTALL_DIR%\app.py" (
    echo  Already installed - checking for updates...
    cd /d "%INSTALL_DIR%"
    git pull origin main >nul 2>&1
    if %errorlevel% neq 0 (
        echo  Could not auto-update - will use existing version.
    ) else (
        echo  Updated to latest version!
    )
) else (
    git --version >nul 2>&1
    if %errorlevel% equ 0 (
        echo  Cloning LeadsOSINT repository...
        git clone https://github.com/Jude-Ogwu/LeadsOSINT.git "%INSTALL_DIR%"
    ) else (
        echo  Downloading LeadsOSINT as ZIP...
        curl -L -o "%TEMP%\leadsosint.zip" "https://github.com/Jude-Ogwu/LeadsOSINT/archive/refs/heads/main.zip"
        if %errorlevel% neq 0 (
            echo.
            echo  ERROR: Could not download LeadsOSINT.
            echo  Please check your internet connection and try again.
            pause
            exit /b 1
        )
        echo  Extracting files...
        mkdir "%INSTALL_DIR%" >nul 2>&1
        powershell -Command "Expand-Archive -Path '%TEMP%\leadsosint.zip' -DestinationPath '%TEMP%\leadsosint_extracted' -Force"
        xcopy /E /I /Y "%TEMP%\leadsosint_extracted\LeadsOSINT-main" "%INSTALL_DIR%" >nul
        rmdir /S /Q "%TEMP%\leadsosint_extracted" >nul 2>&1
        del "%TEMP%\leadsosint.zip" >nul 2>&1
    )
)

if not exist "%INSTALL_DIR%\app.py" (
    echo.
    echo  ERROR: app.py not found in %INSTALL_DIR%
    echo  Installation may have failed. Please try again.
    pause
    exit /b 1
)

rem -- Step 3: Python virtual environment
echo.
echo [3/5] Setting up Python environment...
cd /d "%INSTALL_DIR%"
if not exist "venv\Scripts\python.exe" (
    echo  Creating virtual environment...
    python -m venv venv
)
echo  Installing required packages (first run takes 2-3 mins)...
venv\Scripts\python -m pip install --timeout 120 --retries 5 -r requirements.txt -q
if %errorlevel% neq 0 (
    echo  First attempt had issues. Retrying...
    venv\Scripts\python -m pip install --timeout 180 --retries 5 -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo  WARNING: Some packages may not have installed correctly.
        echo  The app may still work. Continuing...
    )
)
echo  Packages ready!

rem -- Step 4: Playwright browser
echo.
echo [4/5] Setting up browser engine...
if not exist "%USERPROFILE%\AppData\Local\ms-playwright" (
    echo  Downloading Chromium browser (one-time, ~150MB)...
    venv\Scripts\playwright install chromium
) else (
    echo  Browser engine already installed.
)

rem -- Step 5: Create .env if missing
echo.
echo [5/5] Configuring app...
if not exist ".env" (
    (
        echo BD_API_KEY=88c5b773-fbd9-4602-abcc-3772d16891cb
        echo PORT=5050
        echo OUT_DIR=%INSTALL_DIR%\data
    ) > .env
    mkdir data >nul 2>&1
    echo  Configuration created.
) else (
    echo  Configuration already exists.
)

rem -- Launch App
echo.
echo  ============================================
echo    Setup complete! Launching LeadsOSINT...
echo  ============================================
echo.
echo  App will open in your browser shortly.
echo  Login: admin / AdminOSINT2026!
echo.
echo  To stop the app: close this window.
echo  To restart: double-click Setup.bat again.
echo.

rem Open browser after 4 seconds
start "" /B powershell -Command "Start-Sleep 4; Start-Process '%APP_URL%'"

rem Start Flask
venv\Scripts\python app.py

echo.
echo  LeadsOSINT has stopped.
pause
