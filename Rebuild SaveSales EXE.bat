@echo off
setlocal
cd /d "%~dp0"

echo Closing any old SaveSales.exe...
taskkill /IM SaveSales.exe /F >nul 2>&1

echo Checking Python 3.12...
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 was not found.
  pause
  exit /b 1
)

echo Installing/updating build requirements...
py -3.12 -m pip install pyinstaller customtkinter pillow psutil flask >nul
if errorlevel 1 (
  echo Failed to install build requirements.
  pause
  exit /b 1
)

echo Building the CURRENT SaveSales source with the SaveSales logo...
py -3.12 -m PyInstaller --noconfirm --clean --onefile --windowed --name SaveSales --icon "%~dp0savesales.ico" --collect-all customtkinter --collect-all PIL main.py
if errorlevel 1 (
  echo.
  echo BUILD FAILED. Read the error above.
  pause
  exit /b 1
)

copy /Y "%~dp0dist\SaveSales.exe" "%~dp0SaveSales.exe" >nul
if errorlevel 1 (
  echo Could not replace SaveSales.exe. Make sure it is closed and try again.
  pause
  exit /b 1
)

echo.
echo SaveSales.exe was rebuilt successfully from the CURRENT files.
echo Opening it now...
start "" "%~dp0SaveSales.exe"
timeout /t 2 >nul
exit /b 0
