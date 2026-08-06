@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PERIODS="
set /p "PERIODS=Input periods, example 187 188 189: "
if "%PERIODS%"=="" (
  echo Periods are empty.
  pause
  exit /b 1
)

echo.
echo ===== Multi-period single-pass start =====
call py -3.10 scripts\lottery_head_multi_period.py %PERIODS%
if errorlevel 1 (
  echo.
  echo Multi-period scrape failed.
  pause
  exit /b 1
)

echo.
echo Finished. recent_10_cache.json was not refreshed.
pause
