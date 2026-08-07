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
rem               14 add 15 commit 16 push 17 zone-pages 18 indicator-pages
rem               19 already-running
rem   (2026-07-24: 이메일/인스타 자동 발행 제거. 네이버는 자동 발행이 아니라
rem    drafts/ 초안 생성만 남아 있고(gitignore, 비치명적 WARN) 계속 실행된다.
rem    rc=18은 옛 newsletter 코드가 아니라 make_indicator_pages 실패에 쓴다
rem    — 2026-08-04 감사에서 표와 실물이 어긋난 것을 맞춤.)
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

python tools\make_sido_pages.py
if errorlevel 1 (
  echo ERROR: make_sido_pages failed - newsletter skipped
  exit /b 17
)

python tools\make_indicator_pages.py
if errorlevel 1 (
  echo ERROR: make_indicator_pages failed
  exit /b 18
)

rem 이중 구현 정합성 검사(check_dual_calc)는 2026-08-06에 폐지했다.
rem 점수를 tools\sido_zones.py가 빌드 시점에 계산해 ADV.sido로 싣고 홈·지역
rem 페이지가 그걸 읽기만 하므로, 갈릴 구현 자체가 없다.

rem NOTE: this list must cover every file the steps above write.
rem split_data.py emits 5 files (core/trend/rest/sgg/size) and
rem make_indicator_pages.py emits jeonse-ratio/ and moveins/.
rem A file missing here is silently never deployed (2026-08-04 audit:
rem data-sgg.json and data-size.json were absent from every list).
git diff --quiet data.js data-core.js data-rest.json data-trend.json data-sgg.json data-size.json index.html share\weekly-map.png zone sitemap.xml jeonse-ratio moveins
if errorlevel 1 (
  git add data.js data-core.js data-rest.json data-trend.json data-sgg.json data-size.json index.html share\weekly-map.png zone sitemap.xml jeonse-ratio moveins tools\data\.home_stamp
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
