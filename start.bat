@echo off
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
echo 손님 신호등을 켭니다. 브라우저가 자동으로 열립니다. 끄려면 이 창을 닫으세요.
python -m jeju_agent.server
pause
