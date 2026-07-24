@echo off
rem ============================================================
rem aptweather weekly stats update (local runner)
rem - KOSIS blocks GitHub-hosted runners (foreign IP), so run locally.
rem - API keys: %USERPROFILE%\.aptweather_keys.bat (NOT in the repo)
rem - Task Scheduler: daily 18:00 + Thu 13/15 + Fri 09:30 (StartWhenAvailable)
rem
rem FAIL-FAST POLICY (added 2026-07-18)
rem   Every step is checked. If data update or git push fails, the script
rem   ABORTS so the live site is never left partially updated.
rem   All output goes to logs\weekly-YYYY-MM-DD.log and the exit code is
rem   propagated so Task Scheduler shows a non-zero "Last Run Result".
rem   Notification is handled externally by .github/workflows/watchdog.yml
rem   (a local script cannot report that it never ran).
rem
rem   exit codes: 10 keys 11 pull 12 update 20 split 13 share
rem               14 add 15 commit 16 push 17 zone-pages 19 already-running
rem   (2026-07-24: 이메일/인스타/네이버 발행 채널 전면 제거 — 데이터 갱신·배포·
rem    IndexNow 핑만 남음. 이전 rc=18 newsletter 코드는 폐지.)
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
if not "%RC%"=="19" rmdir /s /q "%LOCK%" 2>nul
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
if not errorlevel 1 goto :lock_ok
rem Lock exists. Reclaim only if its stamp is 24h+ stale (a normal run finishes
rem in minutes, so a day-old stamp means a prior run died holding it). Do NOT
rem shorten this: scheduled runs are only 2h apart, and a short window could
rem steal a still-live lock and double-send. forfiles /d -1 = stamp 24h+ untouched.
rem NOTE: kept as goto (not a paren block) on purpose -- an echo containing
rem escaped parens ^(like this^) inside a ( ) block corrupts exit /b in cmd.
forfiles /p "%LOCK%" /m stamp.txt /d -1 >nul 2>&1
if not errorlevel 1 goto :lock_reclaim
echo ERROR: another run holds the lock ^(%LOCK%^) - aborting
echo If no run is active, delete that folder by hand.
exit /b 19
:lock_reclaim
echo WARN: stale lock ^(24h+^) found - reclaiming
rmdir /s /q "%LOCK%"
mkdir "%LOCK%"
:lock_ok
rem Stamp for staleness detection by the next run.
type nul > "%LOCK%\stamp.txt"

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

rem split data.js -> data-core.js / data-trend.json / data-rest.json.
rem home reads data-core.js, so skipping this step leaves home stale.
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

rem 이중 구현 정합성 검사. 아공맵 스코어는 index.html scCalc()와
rem make_zone_pages.py calc() 양쪽에 있어서, 한쪽만 고치면 같은 지표가
rem 홈과 zone 페이지에 다르게 나온다(2026-07-20 실제 발생, 홈이 2.4배).
rem 비치명적 — 불일치가 통계 갱신을 막지는 않게 WARN만 남긴다.
python tools\check_dual_calc.py
if errorlevel 1 echo WARN: scCalc vs calc mismatch - home and zone pages differ

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

python tools\ping_indexnow.py --sitemap
if errorlevel 1 echo WARN: ping_indexnow failed

echo ===== update end %date% %time% =====
exit /b 0
