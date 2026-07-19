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
rem   exit codes: 10 keys 11 pull 12 update 20 split 13 share
rem               14 add 15 commit 16 push 17 zone-pages 18 newsletter
rem               19 already-running
rem   Newsletter send failure does NOT abort (stats are already live),
rem   but it is reported as rc=18 so a silent non-send cannot look like OK.
rem ============================================================
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."

for /f %%i in ('python -c "import datetime;print(datetime.date.today().isoformat())"') do set TODAY=%%i
if "%TODAY%"=="" set TODAY=unknown
if not exist logs mkdir logs
set LOG=logs\weekly-%TODAY%.log
set LOCK=%~dp0..\.batch.lock

call :main >> "%LOG%" 2>&1
set RC=%ERRORLEVEL%
rem Release the lock unless we aborted *because* someone else held it (rc=19).
if not "%RC%"=="19" rmdir "%LOCK%" 2>nul
if not "%RC%"=="0" (
  echo [%date% %time%] FAILED rc=%RC% - see %LOG%
  echo [%date% %time%] FAILED rc=%RC% >> "%LOG%"
  exit /b %RC%
)
echo [%date% %time%] OK - see %LOG%
exit /b 0

:main
echo ===== update start %date% %time% =====

rem Concurrency lock. Task Scheduler's IgnoreNew only guards its own instances;
rem a manual run and a scheduled run could still overlap and double-send.
rem mkdir is atomic on NTFS, so it works as a lock even under a race.
mkdir "%LOCK%" 2>nul
if errorlevel 1 (
  echo ERROR: another run holds the lock ^(%LOCK%^) - aborting
  echo If no run is active, delete that folder by hand.
  exit /b 19
)

if not exist "%USERPROFILE%\.aptweather_keys.bat" (
  echo ERROR: key file not found
  exit /b 10
)
call "%USERPROFILE%\.aptweather_keys.bat"

rem A prior run may have died mid-rebase, leaving the repo wedged. Clear it first,
rem otherwise every later run fails at pull forever with no way out.
if exist ".git\rebase-merge" (
  echo WARN: leftover rebase state found - aborting it
  git rebase --abort
)
if exist ".git\rebase-apply" (
  echo WARN: leftover rebase state found - aborting it
  git rebase --abort
)
rem --autostash: a parallel session's uncommitted edits must not wedge the batch.
git pull --rebase --autostash origin main
if errorlevel 1 (
  echo ERROR: git pull failed - aborting before any update
  git rebase --abort 2>nul
  exit /b 11
)

python tools\update_adv_data.py --update
if errorlevel 1 (
  echo ERROR: update_adv_data failed - newsletter skipped
  exit /b 12
)

rem data.js에서 홈 전용 조각(data-core.js)과 나머지(data-rest.json)를 다시 만든다.
rem 이 단계를 빠뜨리면 홈만 지난주 데이터를 계속 보여준다 — data.js는 갱신됐는데
rem 홈이 읽는 건 data-core.js이기 때문이다.
python tools\split_data.py
if errorlevel 1 (
  echo ERROR: split_data failed - newsletter skipped
  exit /b 20
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

git diff --quiet data.js data-core.js data-rest.json data-trend.json index.html share\weekly-map.png zone sitemap.xml
if errorlevel 1 (
  git add data.js data-core.js data-rest.json data-trend.json index.html share\weekly-map.png zone sitemap.xml
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

set SENDRC=0

python tools\make_naver_post.py
if errorlevel 1 echo WARN: make_naver_post failed

python tools\send_newsletter.py
if errorlevel 1 (
  echo ERROR: send_newsletter failed - stats are live but mail did NOT go out
  set SENDRC=18
)

python tools\send_instagram.py
if errorlevel 1 echo WARN: send_instagram failed

python tools\ping_indexnow.py --sitemap
if errorlevel 1 echo WARN: ping_indexnow failed

echo ===== update end %date% %time% =====
exit /b %SENDRC%
