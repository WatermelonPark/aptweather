@echo off
rem ============================================================
rem aptweather weekly stats update (local runner)
rem - KOSIS blocks GitHub-hosted runners (foreign IP), so run locally.
rem - API keys: %USERPROFILE%\.aptweather_keys.bat (NOT in the repo)
rem - Task Scheduler: daily 18:00 + Thu 13/15 + Fri 09:30 (StartWhenAvailable)
rem
rem FAIL-FAST POLICY (added 2026-07-18)
rem   Every step is checked. If data update or git push fails, the script
rem   ABORTS BEFORE send_newsletter so subscribers are never told about
rem   stats that did not actually reach the live site.
rem   All output goes to logs\weekly-YYYY-MM-DD.log and the exit code is
rem   propagated so Task Scheduler shows a non-zero "Last Run Result".
rem   Notification is handled externally by .github/workflows/watchdog.yml
rem   (a local script cannot report that it never ran).
rem
rem   exit codes: 10 keys 11 pull 12 update 13 share
rem               14 add 15 commit 16 push 17 zone-pages
rem ============================================================
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."

for /f %%i in ('python -c "import datetime;print(datetime.date.today().isoformat())"') do set TODAY=%%i
if "%TODAY%"=="" set TODAY=unknown
if not exist logs mkdir logs
set LOG=logs\weekly-%TODAY%.log

call :main >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo [%date% %time%] FAILED rc=%RC% - see %LOG%
  echo [%date% %time%] FAILED rc=%RC% >> "%LOG%"
  exit /b %RC%
)
echo [%date% %time%] OK - see %LOG%
exit /b 0

:main
echo ===== update start %date% %time% =====

if not exist "%USERPROFILE%\.aptweather_keys.bat" (
  echo ERROR: key file not found
  exit /b 10
)
call "%USERPROFILE%\.aptweather_keys.bat"

git pull --rebase origin main
if errorlevel 1 (
  echo ERROR: git pull failed - aborting before any update
  exit /b 11
)

python tools\update_adv_data.py --update
if errorlevel 1 (
  echo ERROR: update_adv_data failed - newsletter skipped
  exit /b 12
)

python tools\make_weekly_share.py
if errorlevel 1 (
  echo ERROR: make_weekly_share failed - newsletter skipped
  exit /b 13
)

python tools\make_zone_pages.py
if errorlevel 1 (
  echo ERROR: make_zone_pages failed - newsletter skipped
  exit /b 17
)

git diff --quiet data.js index.html share\weekly-map.png zone sitemap.xml
if errorlevel 1 (
  git add data.js index.html share\weekly-map.png zone sitemap.xml
  if errorlevel 1 (
    echo ERROR: git add failed
    exit /b 14
  )
  git commit -m "stats: weekly auto-update (KOSIS, local)"
  if errorlevel 1 (
    echo ERROR: git commit failed
    exit /b 15
  )
  git push origin main
  if errorlevel 1 (
    echo ERROR: git push failed - site NOT updated, newsletter skipped
    exit /b 16
  )
  echo changes committed and pushed
) else (
  echo no changes
)

python tools\make_naver_post.py
if errorlevel 1 echo WARN: make_naver_post failed

python tools\send_newsletter.py
if errorlevel 1 echo WARN: send_newsletter failed

python tools\send_instagram.py
if errorlevel 1 echo WARN: send_instagram failed

python tools\ping_indexnow.py / /weekly/
if errorlevel 1 echo WARN: ping_indexnow failed

echo ===== update end %date% %time% =====
exit /b 0
