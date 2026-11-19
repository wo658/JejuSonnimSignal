"""손님 신호등 에이전트.

AI(Claude)가 하는 판단 (모든 흐름은 질문 의도에서 시작한다):
- 사장님 말에서 의도(한 달·여러 달 비교·1년 흐름·국적·받을 자료·범위 밖)와 동네·달을 알아듣고, 빠지면 되묻는다
- 의도에 맞는 도구를 골라 순서를 정한다 (1년 흐름 / 한 달 결과지 / 센터 파일 확인 / 받을 자료 안내)
- 답에 맞는 카드를 직접 설계한다 (신호·막대 차트·선 차트·국적·할 일·달 칩·짧은 글·받을 자료). 필요 없으면 띄우지 않는다
- 범위 밖 질문(매출 예측, 옆 가게 등)은 답할 수 있는 질문으로 바꿔 제안한다
숫자는 도구(계산 코드)만 낸다. 카드의 배율·신호·비중도 cards.py가 계산 결과로 채운다.
LLM이 쓰지 못하면 같은 흐름을 규칙으로 처리한다(틀 문장 모드).
"""
from __future__ import annotations

import json
import re

from . import cards, centercsv, config, data, llm, report

SYSTEM = """너는 '손님 신호등'이다. 제주빅데이터센터 PC에서 제주 가게 사장님(데이터·컴퓨터가 익숙하지 않은 도민)을 돕는다.
할 일: 사장님 동네(읍면동)에 외국인·육지·동네 손님이 예년에 1년 평균보다 많았는지(북적·보통·한산) 보여 주고 무엇을 준비할지 알려 준다.

일하는 순서:
1. 질문의 의도를 먼저 파악한다. 한 달이 궁금한지, 여러 달을 견주는지(쉬기 좋은 달, 바쁜 철, 여름 석 달 등), 1년 흐름인지, 외국인 국적인지, 센터 자료를 묻는지, 범위 밖인지.
2. 의도에 맞는 도구만 쓴다.
   - 여러 달·1년·"언제"를 묻는 질문은 year_overview를 한 번 부른다. make_report를 달마다 여러 번 부르지 않는다.
   - 한 달의 할 일·근거가 필요하면 make_report를 부른다.
   - 사장님이 센터 파일을 넣었다고 하면 check_center_files를 먼저 부른다. 센터 자료를 묻거나 더 필요하면 order_center_data를 부른다.
3. 화면에 보여 줄 게 있으면 마지막에 show_card를 한 번 부른다. 카드는 답을 돕는 블록만 1~4개 고른다. 말로 충분하면 부르지 않는다.
   - signals: 특정 손님·달의 신호 (한 달이면 세 손님, 비교면 같은 손님의 여러 달)
   - bar: 한 손님의 달별 배율 막대 (어느 달이 튀는지)
   - line: 여러 손님의 1년 흐름 선 (계절 흐름, 쉬기 좋은 달). highlight로 강조할 달을 고른다
   - nations: 그 달 외국인 국적 비중
   - actions: 할 일 (make_report의 할 일을 바탕으로, 질문에 맞게 고르고 줄인다)
   - chips: 달이나 짧은 말 묶음 (예: 조용했던 달)
   - text: 한 줄 메모
   - order: 센터에서 받을 자료 안내
   카드의 숫자는 서버가 계산 결과로 채운다. 블록에는 어떤 손님·달을 보일지만 적는다.

규칙:
- 숫자는 도구 결과에 있는 것만 쓴다. 숫자를 지어내거나 바꾸지 않는다.
- 동네를 모르면 도구를 쓰기 전에 짧게 되묻는다. 동네는 list_neighborhoods에 있는 것만 된다. 달은 의도에 따라 없어도 된다.
- 다음 질문은 답하지 않는다: 매출 예측, 다른 가게 정보, 창업 성공 여부, 지원금. 대신 데이터로 답할 수 있는 가까운 질문을 한 줄로 제안한다. 이때 카드는 띄우지 않는다.
- 신호는 예년 기록이지 올해 예측이 아니라는 점을 흐리지 않는다.
- 말투: 토스처럼 짧고 친근한 해요체. 두세 문장. 결론부터 말한다. 전문용어·영어 약어·마크다운 기호를 쓰지 않는다.
- 한계나 데이터 설명을 길게 늘어놓지 않는다. 필요하면 "지난 기록이라 올해 예측은 아니에요" 한 줄만."""

_EMD = {"type": "string"}
_MONTH = {"type": "integer", "minimum": 1, "maximum": 12}
_GUEST = {"type": "string", "enum": ["foreign", "mainland", "local"]}
_MONTHS = {"type": "array", "items": _MONTH}
TOOLS = [
    {"name": "list_neighborhoods", "description": "결과를 낼 수 있는 읍면동 목록과 데이터 기준 시점을 돌려준다.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "year_overview",
     "description": "한 동네의 1~12월 세 손님 신호와 배율, 조용했던 달·붐볐던 달을 돌려준다. 여러 달을 견주거나 '언제'를 묻는 질문에 쓴다.",
     "input_schema": {"type": "object", "properties": {"emd": _EMD}, "required": ["emd"], "additionalProperties": False}},
    {"name": "make_report",
     "description": "읍면동과 달(1~12)로 한 달 결과지를 만든다. 세 손님 신호, 할 일, 근거, 외국인 국적 상위, 되물을 것을 돌려준다.",
     "input_schema": {"type": "object", "properties": {"emd": _EMD, "month": _MONTH},
                      "required": ["emd", "month"], "additionalProperties": False}},
    {"name": "check_center_files",
     "description": "사장님이 넣은 센터 CSV 파일을 헤더로 알아보고 표 종류·들어 있는 달·문제를 돌려준다. 값은 돌려주지 않는다.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "order_center_data",
     "description": "더 정확하게 보려면 센터 PC에서 받아 올 자료(이름·고를 것·달)를 쉬운 말로 돌려준다.",
     "input_schema": {"type": "object", "properties": {"emd": _EMD, "month": _MONTH},
                      "required": ["emd", "month"], "additionalProperties": False}},
    {"name": "show_card",
     "description": "답 아래에 보여 줄 카드를 설계한다. 블록 1~4개. 숫자는 서버가 계산 결과로 채우므로 블록에는 손님·달만 적는다.",
     "input_schema": {"type": "object", "properties": {
         "emd": _EMD,
         "title": {"type": "string", "description": "짧은 제목. 예: 애월읍 쉬기 좋은 달"},
         "subtitle": {"type": "string"},
         "blocks": {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {
             "type": {"type": "string", "enum": ["signals", "bar", "line", "nations", "actions", "chips", "text", "order"]},
             "title": {"type": "string"},
             "items": {"type": "array", "description": "signals: [{guest, month}], actions: [{title, detail}], chips: [문자열]",
                       "items": {}},
             "guest": _GUEST, "guests": {"type": "array", "items": _GUEST},
             "month": _MONTH, "months": _MONTHS, "highlight": _MONTHS,
             "tone": {"type": "string", "enum": ["busy", "mid", "calm"]},
             "text": {"type": "string"}},
             "required": ["type"]}}},
         "required": ["emd", "blocks"], "additionalProperties": False}},
]


class Session:
    def __init__(self, snap: data.Snapshot):
        self.snap = snap
        self.uploads: list[centercsv.Inspected] = []
        self.messages: list = []
        self.report: dict | None = None
        self.card: dict | None = None
        self.mode = "llm"

    # ---------- 도구 ----------
    def tool(self, name: str, args: dict) -> dict:
        emd = args.get("emd", "")
        if name in ("year_overview", "make_report", "order_center_data", "show_card") and emd not in self.snap.emds:
            return {"오류": f"{emd}은 아직 볼 수 없어요.", "가능": self.snap.emds}
        if name == "list_neighborhoods":
            return {"읍면동": self.snap.emds, "기록": self.snap.last_ym(), "가상데이터": self.snap.is_dummy}
        if name == "year_overview":
            return cards.year_for_llm(cards.year_overview(self.snap, emd))
        if name == "make_report":
            self.report = report.build(self.snap, emd, int(args.get("month", 0)), self.uploads)
            return report.summary_for_llm(self.report)
        if name == "check_center_files":
            return {"파일": [{"표": u.title, "달": u.months, "문제": u.problems} for u in self.uploads] or "넣은 파일 없음"}
        if name == "order_center_data":
            return order(self.snap, emd, int(args.get("month", 1)))
        if name == "show_card":
            self.card = cards.build(self.snap, args, order)
            return {"보여줌": bool(self.card), "블록": [b["type"] for b in (self.card or {}).get("blocks", [])]}
        return {"오류": "없는 도구"}

    # ---------- 대화 ----------
    def ask(self, text: str) -> dict:
        self.card = None
        if llm.available():
            try:
                return self._ask_llm(text)
            except llm.LLMUnavailable as e:
                self.mode = f"틀 문장 모드 (LLM 연결 안 됨: {str(e)[:80]})"
        else:
            self.mode = "틀 문장 모드 (LLM 꺼짐)"
        return self._ask_rules(text)

    def _ask_llm(self, text: str) -> dict:
        self.mode = "llm"
        self.messages.append({"role": "user", "content": llm.scrub(text)})
        trace = []
        for _ in range(8):
            resp = llm.create(SYSTEM, self.messages, TOOLS)
            content = resp.get("content", [])
            self.messages.append({"role": "assistant", "content": content})
            if resp.get("stop_reason") == "refusal":
                return self._reply("이 질문은 답하기 어려워요. 동네와 달을 알려 주시면 손님 흐름을 보여 드릴게요.", trace)
            uses = [b for b in content if b.get("type") == "tool_use"]
            if not uses:
                answer = " ".join(b.get("text", "") for b in content if b.get("type") == "text").strip()
                return self._reply(answer, trace)
            results = []
            for u in uses:
                out = self.tool(u["name"], u.get("input") or {})
                trace.append({"tool": u["name"], "input": u.get("input")})
                results.append({"type": "tool_result", "tool_use_id": u["id"],
                                "content": json.dumps(out, ensure_ascii=False)})
            self.messages.append({"role": "user", "content": results})
        return self._reply("조금 오래 걸리네요. 다시 한번 물어봐 주시겠어요?", trace)

    def _ask_rules(self, text: str) -> dict:
        """AI 없이: 같은 의도 구분을 규칙으로 하고, 정해진 조합으로 카드를 만든다."""
        off = out_of_scope(text)
        if off:
            return self._reply(off, [])
        emd = next((e for e in self.snap.emds if e in text or e[:-1] in text), None)
        if emd is None and self.report:
            emd = self.report["emd"]
        if not emd:
            return self._reply(f"어느 동네에서 장사하세요? 지금은 {', '.join(self.snap.emds)}을 볼 수 있어요.", [])
        month = parse_month(text)
        if wants_year(text) and not explicit_month(text):
            y = cards.year_overview(self.snap, emd)
            self.card = cards.build(self.snap, cards.year_spec(y))
            return self._reply(" ".join(cards.year_sentences(y, bool(re.search(r"바쁘|바빠|붐비|많", text)))), [{"tool": "year_overview", "input": {"emd": emd}}])
        month = month or (self.report["month"] if self.report else None)
        if not month:
            return self._reply("몇 월이 궁금하세요? 1년 흐름이 궁금하면 '언제가 바빠요?'처럼 물어보세요.", [])
        self.report = report.build(self.snap, emd, month, self.uploads)
        self.card = cards.build(self.snap, cards.month_spec(self.report))
        return self._reply(" ".join(report.template_sentences(self.report)),
                           [{"tool": "make_report", "input": {"emd": emd, "month": month}}])

    def _reply(self, answer: str, trace: list) -> dict:
        return {"answer": answer, "card": self.card, "report": self.report, "trace": trace, "mode": self.mode}


def wants_year(text: str) -> bool:
    return bool(re.search(r"언제|어느\s*달|몇\s*월|가장|제일|1년|일\s*년|한\s*해|달별|철|시즌", text))


def explicit_month(text: str) -> bool:
    return bool(re.search(r"(1[0-2]|[1-9])\s*월", text))


def order(snap: data.Snapshot, emd: str, month: int) -> dict:
    """센터 자료 안내: 이미 들어 있는 공개 데이터와, 센터 PC에서 받아 오면 좋은 표를 쉬운 말로."""
    years = sorted({int(ym[:4]) for ym in snap.pop.get(emd, {})} - set(range(config.FROM_YEAR)))
    yms = [f"{y}년 {month}월" for y in years if f"{y}{month:02d}" <= snap.last_ym()]
    return {
        "이미있음": "동네에 다녀간 사람 수 (제주데이터허브 공개 데이터, 미리 넣어 둠)",
        "왜": "지금 신호는 사람 수로 본 거예요. 센터에만 있는 카드 결제 기록을 넣으면 실제로 돈을 쓴 손님까지 확인해요.",
        "센터에서받기": [
            {"이름": "우리 동네 카드 결제", "표": "카드 이용 현황(읍면동)_v02",
             "고를것": [f"동네: {emd}", "업종: 고르지 않기"], "달": yms,
             "쓰임": "어느 달에 손님이 실제로 돈을 많이 썼는지 확인해요"},
        ],
        "안내": "센터 조회 화면에서는 한 번에 한 달씩 받아요. 여러 달이 필요하면 센터 직원에게 부탁하세요.",
    }


def parse_month(text: str) -> int | None:
    m = re.search(r"(1[0-2]|[1-9])\s*월", text)
    if m:
        return int(m.group(1))
    for word, mm in (("설", 2), ("추석", 9), ("겨울", 1), ("봄", 4), ("여름", 8), ("가을", 10)):
        if word in text:
            return mm
    return None


def out_of_scope(text: str) -> str | None:
    if re.search(r"매출.*(얼마|나와|예상)|얼마.*벌", text):
        return "매출은 예측하지 않아요. 대신 예년 이맘때 손님 흐름을 보여 드릴게요. 동네와 달을 알려 주세요."
    if re.search(r"옆\s*가게|다른\s*가게", text):
        return "다른 가게 정보는 볼 수 없어요. 대신 우리 동네 손님이 언제 많은지 볼까요?"
    if re.search(r"잘\s*될|성공|망하", text):
        return "잘될지는 알려 드릴 수 없어요. 대신 그 동네 손님 흐름을 먼저 볼까요?"
    if "지원금" in text:
        return "지원금은 여기서 안내하기 어려워요. 소상공인지원센터나 제주신용보증재단에 물어보세요."
    return None
