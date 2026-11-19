@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [손님 신호등] 설치 확인을 시작합니다.
where python > nul 2> nul
if errorlevel 1 (
  echo.
  echo Python 이 없습니다. https://www.python.org/downloads/ 에서 Python 3.12 이상을 설치하세요.
  echo 설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요. 설치 뒤 이 파일을 다시 실행하세요.
  pause
  exit /b 1
)
python --version
if not exist ".env" (
  copy ".env.example" ".env" > nul
  echo .env 파일을 만들었습니다. 메모장으로 열어 키를 넣으세요. (매뉴얼 3단계)
)
echo 추가로 설치할 패키지는 없습니다. (Python 표준 라이브러리만 사용)
set PYTHONPATH=%~dp0src
python -m unittest discover -s tests
if errorlevel 1 (
  echo 자체 시험이 실패했습니다. 매뉴얼의 "문제가 생기면" 을 보세요.
  pause
  exit /b 1
)
echo.
echo 설치 확인 끝. start.bat 을 두 번 클릭해 실행하세요.
pause
