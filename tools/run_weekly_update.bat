@echo off
rem ============================================================
rem aptweather weekly stats update (local runner)
rem - KOSIS blocks GitHub-hosted runners (foreign IP), so run locally.
rem - API keys: %USERPROFILE%\.aptweather_keys.bat (NOT in the repo)
rem - Task Scheduler: every Friday 09:30 (runs at next boot if missed)
rem ============================================================
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

if not exist "%USERPROFILE%\.aptweather_keys.bat" (
  echo [%date% %time%] ERROR: key file not found
  exit /b 1
)
call "%USERPROFILE%\.aptweather_keys.bat"

cd /d "%~dp0.."
echo [%date% %time%] ===== update start =====

git pull --rebase origin main
python tools\update_adv_data.py --update

git diff --quiet index.html
if errorlevel 1 (
  git add index.html
  git commit -m "stats: weekly auto-update (KOSIS, local)"
  git push origin main
  echo [%date% %time%] changes committed and pushed
) else (
  echo [%date% %time%] no changes
)

python tools\send_newsletter.py
echo [%date% %time%] ===== update end =====
