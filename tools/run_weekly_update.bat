@echo off
rem ============================================================
rem aptweather 주간 통계 갱신 (로컬 실행용)
rem - GitHub Actions 러너에서 KOSIS가 해외 IP를 차단해 로컬에서 돌린다.
rem - API 키는 %USERPROFILE%\.aptweather_keys.bat 에서 읽는다 (저장소에 없음).
rem - 작업 스케줄러: 매주 금 09:30 (꺼져 있었으면 켜질 때 실행)
rem ============================================================
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

if not exist "%USERPROFILE%\.aptweather_keys.bat" (
  echo [%date% %time%] 키 파일 없음: %USERPROFILE%\.aptweather_keys.bat
  exit /b 1
)
call "%USERPROFILE%\.aptweather_keys.bat"

cd /d "%~dp0.."
echo [%date% %time%] ===== 갱신 시작 =====

git pull --rebase origin main
python tools\update_adv_data.py --update

git diff --quiet index.html
if errorlevel 1 (
  git add index.html
  git commit -m "통계 데이터 자동 갱신 (KOSIS·로컬)"
  git push origin main
  echo [%date% %time%] 변경 커밋·푸시 완료
) else (
  echo [%date% %time%] 변경 없음
)

python tools\send_newsletter.py
echo [%date% %time%] ===== 갱신 끝 =====
