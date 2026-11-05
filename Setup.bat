@echo off
setlocal EnableDelayedExpansion
title LeadsOSINT Setup
color 0A

echo.
echo  ============================================
echo    LeadsOSINT - Windows Setup ^& Launcher
echo  ============================================
echo.

rem Set install directory
set "INSTALL_DIR=%USERPROFILE%\LeadsOSINT"
set "APP_URL=http://localhost:5050"

rem -------------------------------------------------------
rem Step 1: Check Python
rem -------------------------------------------------------
echo [1/5] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  Python not found. Downloading Python 3.11...
    echo  Please wait - this only happens once.
    echo.
    if exist "%TEMP%\python_installer.exe" del "%TEMP%\python_installer.exe" >nul 2>&1
    curl.exe -L --retry 3 --retry-delay 3 -o "%TEMP%\python_installer.exe" "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    if not exist "%TEMP%\python_installer.exe" (
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
    echo.
    echo  Python installed! Please CLOSE this window and double-click Setup.bat again.
    pause
    exit /b 0
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  Found: %%v

rem -------------------------------------------------------
rem Step 2: Get / Update LeadsOSINT files
rem -------------------------------------------------------
echo.
echo [2/5] Getting LeadsOSINT files...
if exist "%INSTALL_DIR%\app.py" (
    echo  Already installed - checking for updates...
    git --version >nul 2>&1
    if %errorlevel% equ 0 (
        cd /d "%INSTALL_DIR%"
        git pull >nul 2>&1
        echo  Updated via git.
    ) else (
        echo  Downloading latest update...
        if exist "%TEMP%\leadsosint.zip" del "%TEMP%\leadsosint.zip" >nul 2>&1
        curl.exe -L --retry 3 --retry-delay 3 -o "%TEMP%\leadsosint.zip" "https://github.com/Jude-Ogwu/LeadsOSINT/archive/refs/heads/main.zip"
        if exist "%TEMP%\leadsosint.zip" (
            echo  Applying update (preserving your data)...
            powershell -Command "Expand-Archive -Path '%TEMP%\leadsosint.zip' -DestinationPath '%TEMP%\leadsosint_ext' -Force; Get-ChildItem '%TEMP%\leadsosint_ext\LeadsOSINT-main' | Where-Object { $_.Name -notin @('data','.env','jobs_registry.json') } | ForEach-Object { Copy-Item $_.FullName -Destination '%INSTALL_DIR%' -Recurse -Force }; Remove-Item '%TEMP%\leadsosint_ext' -Recurse -Force"
            del "%TEMP%\leadsosint.zip" >nul 2>&1
            echo  Updated!
        ) else (
            echo  Could not download update. Running existing version.
        )
        cd /d "%INSTALL_DIR%"
    )
) else (
    git --version >nul 2>&1
    if %errorlevel% equ 0 (
        echo  Cloning LeadsOSINT repository...
        git clone https://github.com/Jude-Ogwu/LeadsOSINT.git "%INSTALL_DIR%"
    ) else (
        echo  Downloading LeadsOSINT as ZIP...
        if exist "%TEMP%\leadsosint.zip" del "%TEMP%\leadsosint.zip" >nul 2>&1
        curl.exe -L --retry 3 --retry-delay 3 -o "%TEMP%\leadsosint.zip" "https://github.com/Jude-Ogwu/LeadsOSINT/archive/refs/heads/main.zip"
        if not exist "%TEMP%\leadsosint.zip" (
            echo.
            echo  ERROR: Could not download LeadsOSINT.
            echo  Please check your internet connection and try again.
            pause
            exit /b 1
        )
        echo  Extracting files...
        mkdir "%INSTALL_DIR%" >nul 2>&1
        powershell -Command "Expand-Archive -Path '%TEMP%\leadsosint.zip' -DestinationPath '%TEMP%\leadsosint_ext' -Force; Copy-Item -Path '%TEMP%\leadsosint_ext\LeadsOSINT-main\*' -Destination '%INSTALL_DIR%' -Recurse -Force; Remove-Item '%TEMP%\leadsosint_ext' -Recurse -Force"
        del "%TEMP%\leadsosint.zip" >nul 2>&1
    )
)

if not exist "%INSTALL_DIR%\app.py" (
    echo.
    echo  ERROR: app.py not found. Installation failed. Please try again.
    pause
    exit /b 1
)

cd /d "%INSTALL_DIR%"

rem -------------------------------------------------------
rem Step 3: Python packages
rem -------------------------------------------------------
echo.
echo [3/5] Setting up Python environment...
if not exist "venv\Scripts\python.exe" (
    echo  Creating virtual environment...
    python -m venv venv
)
echo  Installing packages (first run takes 2-3 mins)...
venv\Scripts\python -m pip install --timeout 120 --retries 5 -q -r requirements.txt
if %errorlevel% neq 0 (
    echo  Retrying package install...
    venv\Scripts\python -m pip install --timeout 180 --retries 5 -r requirements.txt
)
echo  Packages ready!

rem -------------------------------------------------------
rem Step 4: Playwright Chromium
rem -------------------------------------------------------
echo.
echo [4/5] Setting up browser engine...
set "PW_MARKER=%USERPROFILE%\AppData\Local\ms-playwright"
if exist "%PW_MARKER%\" (
    dir /b /ad "%PW_MARKER%\chromium*" >nul 2>&1
    if %errorlevel% equ 0 (
        echo  Browser engine already installed.
        goto pw_done
    )
)
echo  Downloading Chromium (one-time, ~150MB)...
venv\Scripts\playwright install chromium
:pw_done

rem -------------------------------------------------------
rem Step 5: Config
rem -------------------------------------------------------
echo.
echo [5/5] Configuring app...
if not exist ".env" (
    echo BD_API_KEY=74c1d9bb-e468-4005-af28-46368cf62554> .env
    echo PORT=5050>> .env
    mkdir data >nul 2>&1
    echo  Configuration created.
) else (
    echo  Configuration already exists.
)

rem -------------------------------------------------------
rem Launch
rem -------------------------------------------------------
echo.
echo  ============================================
echo    All set! Launching LeadsOSINT...
echo  ============================================
echo.
echo  Access URL:  http://localhost:5050
echo  Login:       admin / AdminOSINT2026!
echo.
echo  App will open in your browser shortly.
echo.
echo  To stop the app: close this window.
echo  To restart: double-click Setup.bat again.
echo.

rem Start Flask
start "LeadsOSINT" /MIN venv\Scripts\python app.py

rem Wait for Flask to start then open browser
timeout /t 5 /nobreak >nul
start "" "%APP_URL%"

echo  LeadsOSINT is running!
echo.
echo  Press any key to STOP the app and close.
pause >nul

rem Stop Flask on exit
taskkill /FI "WindowTitle eq LeadsOSINT" /T /F >nul 2>&1
