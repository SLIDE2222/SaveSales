@echo off
setlocal EnableExtensions

:: Self-elevate because Windows Firewall changes require Administrator rights.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo ================================================
echo        SaveSales LAN Firewall Fix
echo ================================================
echo.

echo Removing old SaveSales firewall rules...
netsh advfirewall firewall delete rule name="SaveSales LAN Program" >nul 2>&1
netsh advfirewall firewall delete rule name="SaveSales LAN Discovery" >nul 2>&1

:: Discovery uses UDP 54545. Restrict inbound traffic to the local subnet.
echo Allowing SaveSales LAN discovery...
netsh advfirewall firewall add rule name="SaveSales LAN Discovery" dir=in action=allow protocol=UDP localport=54545 enable=yes profile=any remoteip=localsubnet >nul
if errorlevel 1 goto :fail

set "FOUND=0"

if exist "%ProgramFiles%\SaveSales\SaveSales.exe" (
    call :allow_program "%ProgramFiles%\SaveSales\SaveSales.exe"
)

if exist "%ProgramFiles(x86)%\SaveSales\SaveSales.exe" (
    call :allow_program "%ProgramFiles(x86)%\SaveSales\SaveSales.exe"
)

if exist "%~dp0SaveSales.exe" (
    call :allow_program "%~dp0SaveSales.exe"
)

if "%FOUND%"=="0" (
    echo.
    echo SaveSales.exe was not found in the normal install folder.
    echo The UDP discovery rule was added, but Windows still needs an inbound
    echo program rule for the actual SaveSales.exe location.
    echo.
    echo Put this BAT beside SaveSales.exe and run it again as Administrator.
    pause
    exit /b 2
)

echo.
echo Firewall rules installed successfully.
echo.
echo IMPORTANT:
echo 1. Run this file on BOTH PCs.
echo 2. Keep both PCs on the same Wi-Fi/router.
echo 3. Close SaveSales on both PCs.
echo 4. Open SaveSales on the PC that already has the saved data FIRST.
echo 5. Then open SaveSales on the second PC and wait about 5-10 seconds.
echo.
echo Your products, sales, employees and tracking data should then synchronize.
echo.
pause
exit /b 0

:allow_program
set "EXE=%~1"
echo Allowing inbound SaveSales sync for:
echo   %EXE%
netsh advfirewall firewall add rule name="SaveSales LAN Program" dir=in action=allow program="%EXE%" enable=yes profile=any remoteip=localsubnet >nul
if errorlevel 1 goto :fail
set "FOUND=1"
exit /b 0

:fail
echo.
echo Windows refused to add the firewall rule.
echo Make sure you approved the Administrator prompt and try again.
pause
exit /b 1
