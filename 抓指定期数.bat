@echo off
setlocal
cd /d "%~dp0"
set "PERIOD="
set /p "PERIOD=Input period, example 150 or 150qi: "
if "%PERIOD%"=="" (
  echo Period is empty.
  pause
  exit /b 1
)
py -3.10 scripts\lottery_head_scraper.py "%PERIOD%"
if errorlevel 1 (
  echo.
  echo Single-period scrape failed.
  pause
  exit /b 1
)
echo.
echo Finished. Check period success/failed txt files in this folder.
pause
