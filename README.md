# 손님 신호등

제주 가게 사장님이 고른 동네(읍면동)와 달에, **외국인·육지·동네 손님**이 예년에 1년 평균보다 많았는지(북적·보통·한산)를 보여 주고 **그래서 무엇을 준비할지** 질문에 맞는 답과 카드(신호·차트·할 일)로 알려 주는 AI 에이전트입니다. 제주 AI·빅데이터 활용 AI Agent 개발 챌린지 출품작.

- 설치·실행: 이 문서 아래 "설치와 실행" (비개발자용 상세판은 [MANUAL.md](MANUAL.md))
- 사용자 매뉴얼·문제 해결: [MANUAL.md](MANUAL.md)
- 데이터 활용 명세: [DATA_SPEC.md](DATA_SPEC.md)
- 결과 설명자료 (문제 정의, 구조, 실행 결과, 검증·한계, 센터 활용 방안): [RESULTS.md](RESULTS.md)
- 기획서 PDF: [docs/기획서.pdf](docs/기획서.pdf)

> **데이터 스냅샷은 이 저장소에 없습니다.** 제주데이터허브 공개 데이터는 원본 재배포가 제한되어(대회 게시판 안내) 대회 제출 zip에만 넣었습니다. 직접 실행하려면 허브 키를 받아 `scripts/collect_hub.py`로 스냅샷을 만드세요 (MANUAL.md A절).

## 설치와 실행 (Windows 11)

1. **Python 3.12 이상 설치**: https://www.python.org/downloads/ → 설치 첫 화면에서 `Add python.exe to PATH` 체크
2. **`setup.bat` 두 번 클릭**: Python 확인, `.env` 만들기, 자체 시험 실행. **추가로 설치할 패키지는 없습니다** (표준 라이브러리만 사용)
3. **`.env` 에 키 넣기** (메모장으로 열기)
   - `ANTHROPIC_API_KEY=` 뒤에 Claude API 키. 비워 두면 AI 없이 틀 문장으로 동작
   - `JEJU_PROJECT_KEY=` 뒤에 제주데이터허브 프로젝트키 (이 저장소에는 데이터 스냅샷이 없어서 필요)
4. **데이터 스냅샷 받기** (이 저장소에서만, 명령 프롬프트에서 한 번):
   ```
   set PYTHONPATH=src
   python -I scripts\collect_hub.py 202201 202608
   ```
5. **`start.bat` 두 번 클릭**: 브라우저가 `http://127.0.0.1:8765` 로 열립니다. 다 쓰면 `초기화`를 누르면 넣은 자료가 지워집니다 (켤 때도 자동 삭제, `.env` 의 `AUTO_DELETE=off` 로 끔)

## 쓰는 것

| 구분 | 내용 |
|---|---|
| 언어·런타임 | Python 3.12 이상 (3.9~3.14 에서 시험). 외부 패키지 없음 |
| 화면 | 로컬 서버 + Chrome·Edge (`127.0.0.1:8765`, 이 PC 안에서만 열림) |
| AI 모델 | Claude Opus 5.5 (`claude-opus-5-5`, effort low), Messages API. 거절 시 서버 측 대체 모델(`fallbacks: default`) |
| 외부 주소 | `https://api.anthropic.com` (AI 문장), `https://open.jejudatahub.net` · `https://jejudatahub.net` (스냅샷을 새로 받을 때만) |
| 데이터 | 제주데이터허브 583·589 스냅샷(`data/snapshot/`, zip 에 포함), 센터 CSV(이용자가 화면에서 넣음) |

## 폴더

```
src/jeju_agent/     에이전트 코드
  agent.py          AI 에이전트 (의도 파악·도구 고르기·되묻기·카드 설계·범위 밖 질문 돌리기), LLM 없을 때 규칙 모드
  cards.py          대화 속 카드 (신호·막대·선 차트·국적·할 일·달 칩), 1년 흐름 계산
  signals.py        신호 계산 (예년 같은 달 ÷ 1년 평균, 두 방법 재확인, 3년 미만 보류)
  rules.py          손님 3종 × 신호 3단계 할 일 규칙표
  centercsv.py      센터 CSV 헤더로 표 알아보기, 빠진 달 찾기
  export_check.py   반출 점검 (10 미만 가림, 역산 방지)
  report.py         한 달 결과 (신호·할 일·국적·근거)
  llm.py            Claude API 호출 (urllib), LLM 전송 기록
  server.py         로컬 서버
  web/index.html    화면
scripts/collect_hub.py   허브 API 로 스냅샷 받기 (JEJU_PROJECT_KEY 필요)
data/sample_center/ 센터 CSV 가상 견본 (값은 무작위)
docs/기획서.pdf      대회 제출 기획서
tests/              자체 시험
setup.bat start.bat
```

## 프롬프트·도구 위치

- 시스템 프롬프트: `src/jeju_agent/agent.py` 의 `SYSTEM`
- 도구 정의(Tool): 같은 파일의 `TOOLS` (list_neighborhoods, year_overview, make_report, check_center_files, order_center_data, show_card)
- 카드 조립: `src/jeju_agent/cards.py` (Claude가 고른 블록에 계산값을 채우고, 계산에 없는 배율이 든 글은 뺌)
- Claude API 호출: `src/jeju_agent/llm.py` (모델·effort는 `.env` 의 `LLM_MODEL`, `LLM_EFFORT` 로 바꿀 수 있음)
- AI에 보내는 내용 기록: 실행 중 `work/llm_log.jsonl`

## 왜 외부 패키지를 안 쓰나

센터 PC는 디지털 서명이 없는 Python 확장 모듈(`.pyd`·`.dll`)을 막을 수 있습니다(대회 게시판 답변). 그래서 Anthropic 공식 SDK(pydantic-core 등 확장 모듈 포함)와 pandas 대신 표준 라이브러리(`urllib`, `csv`, `statistics`, `http.server`)만 씁니다.
