"""손님 신호등 에이전트.

AI(Claude)가 하는 판단:
- 사장님 말에서 동네·달·궁금한 것을 알아듣고, 빠지면 되묻는다
- 어떤 도구를 어떤 순서로 쓸지 정한다 (데이터 주문서 → 센터 파일 검수 → 결과지)
- 넣은 파일이 모자라면 무엇을 더 받을지 안내한다
- 범위 밖 질문(매출 예측, 옆 가게 등)은 답할 수 있는 질문으로 바꿔 제안한다
- 도구가 낸 결과를 사장님 말투 세 문장으로 풀어 쓴다
숫자는 도구(계산 코드)만 낸다. LLM이 쓰지 못하면 같은 흐름을 규칙으로 처리한다(틀 문장 모드).
"""
from __future__ import annotations

import json
import re

from . import centercsv, data, llm, report

SYSTEM = """너는 '손님 신호등'이다. 제주빅데이터센터 PC에서 제주 가게 사장님(데이터·컴퓨터가 익숙하지 않은 도민)을 돕는다.
할 일: 사장님이 고른 동네(읍면동)와 달에, 외국인·육지·동네 손님이 예년에 1년 평균보다 많았는지(북적·보통·한산) 보여 주고 무엇을 준비할지 알려 준다.

규칙:
- 숫자는 도구 결과에 있는 것만 쓴다. 숫자를 지어내거나 바꾸지 않는다.
- 동네나 달을 모르면 도구를 쓰기 전에 짧게 되묻는다. 동네는 list_neighborhoods에 있는 것만 된다.
- 결과지가 필요하면 make_report를 부른다. 사장님이 센터 파일을 넣었다고 하면 check_center_files를 먼저 부른다.
- 센터 자료를 더 받아야 하면 order_center_data로 주문서를 만들고, 그 안내를 그대로 전한다.
- 다음 질문은 답하지 않는다: 매출 예측, 다른 가게 정보, 창업 성공 여부, 지원금. 대신 데이터로 답할 수 있는 가까운 질문을 한 줄로 제안한다.
- 신호는 예년 기록이지 올해 예측이 아니라는 점을 흐리지 않는다.
- 말투: 토스처럼 짧고 친근한 해요체. 두세 문장. 결론부터 말한다. 전문용어·영어 약어·마크다운 기호를 쓰지 않는다.
- 한계나 데이터 설명을 길게 늘어놓지 않는다. 필요하면 "지난 기록이라 올해 예측은 아니에요" 한 줄만."""

TOOLS = [
    {"name": "list_neighborhoods", "description": "결과를 낼 수 있는 읍면동 목록과 데이터 기준 시점을 돌려준다.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "make_report",
     "description": "읍면동과 달(1~12)로 결과지를 만든다. 세 손님 신호(북적·보통·한산), 할 일, 근거, 되물을 것을 돌려준다.",
     "input_schema": {"type": "object", "properties": {"emd": {"type": "string"}, "month": {"type": "integer", "minimum": 1, "maximum": 12}},
                      "required": ["emd", "month"], "additionalProperties": False}},
    {"name": "check_center_files",
     "description": "사장님이 넣은 센터 CSV 파일을 헤더로 알아보고 표 종류·들어 있는 달·문제를 돌려준다. 값은 돌려주지 않는다.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "order_center_data",
     "description": "더 정확하게 보려면 센터 화면에서 받을 표·조건·달을 적은 주문서를 만든다.",
     "input_schema": {"type": "object", "properties": {"emd": {"type": "string"}, "month": {"type": "integer", "minimum": 1, "maximum": 12}},
                      "required": ["emd", "month"], "additionalProperties": False}},
]


class Session:
    def __init__(self, snap: data.Snapshot):
        self.snap = snap
        self.uploads: list[centercsv.Inspected] = []
        self.messages: list = []
        self.report: dict | None = None
        self.mode = "llm"

    # ---------- 도구 ----------
    def tool(self, name: str, args: dict) -> dict:
        if name == "list_neighborhoods":
            return {"읍면동": self.snap.emds, "기록": self.snap.last_ym(), "가상데이터": self.snap.is_dummy}
        if name == "make_report":
            emd, month = args.get("emd", ""), int(args.get("month", 0))
            if emd not in self.snap.emds:
                return {"오류": f"{emd}은 아직 볼 수 없어요.", "가능": self.snap.emds}
            self.report = report.build(self.snap, emd, month, self.uploads)
            return report.summary_for_llm(self.report)
        if name == "check_center_files":
            return {"파일": [{"표": u.title, "달": u.months, "문제": u.problems} for u in self.uploads] or "넣은 파일 없음"}
        if name == "order_center_data":
            return order(self.snap, args.get("emd", ""), int(args.get("month", 1)))
        return {"오류": "없는 도구"}

    # ---------- 대화 ----------
    def ask(self, text: str) -> dict:
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
        for _ in range(6):
            resp = llm.create(SYSTEM, self.messages, TOOLS)
            content = resp.get("content", [])
            self.messages.append({"role": "assistant", "content": content})
            if resp.get("stop_reason") == "refusal":
                return self._reply("이 질문은 답하기 어려워요. 동네와 달을 고르면 손님 흐름을 보여 드릴게요.", trace)
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
        return self._reply("조금 오래 걸리네요. 동네와 달을 다시 알려 주시겠어요?", trace)

    def _ask_rules(self, text: str) -> dict:
        off = out_of_scope(text)
        if off:
            return self._reply(off, [])
        emd = next((e for e in self.snap.emds if e in text or e[:-1] in text), None)
        if emd is None and self.report:
            emd = self.report["emd"]
        month = parse_month(text) or (self.report["month"] if self.report else None)
        if not emd:
            return self._reply(f"어느 동네에서 장사하세요? 지금은 {', '.join(self.snap.emds)}을 볼 수 있어요.", [])
        if not month:
            return self._reply("몇 월이 궁금하세요?", [])
        self.report = report.build(self.snap, emd, month, self.uploads)
        return self._reply(" ".join(report.template_sentences(self.report)),
                           [{"tool": "make_report", "input": {"emd": emd, "month": month}}])

    def _reply(self, answer: str, trace: list) -> dict:
        return {"answer": answer, "report": self.report, "trace": trace, "mode": self.mode}


def order(snap: data.Snapshot, emd: str, month: int) -> dict:
    """데이터 주문서: 공개 데이터는 이미 있음, 센터 표는 무엇을 받을지 안내."""
    years = sorted({int(ym[:4]) for ym in snap.pop.get(emd, {})})
    yms = [f"{y}년 {month}월" for y in years if f"{y}{month:02d}" <= snap.last_ym()]
    return {
        "이미있음": ["허브 583 읍면동 내국인 유동인구", "허브 589 읍면동 외국인 단기체류 유동인구"],
        "센터에서받기": [
            {"표": "카드 이용 현황(읍면동)_v02", "조건": f"법정동 {emd}, 업종은 비워 두기", "달": yms,
             "쓰임": "카드 매출로도 맞춰 볼게요"},
            {"표": "중국인 카드 이용 현황", "조건": "비워 두기", "달": yms, "쓰임": "외국인 손님을 한 번 더 확인할게요"},
        ],
        "안내": "한 번에 한 달씩 받을 수 있어요. 여러 달이 필요하면 센터 담당자에게 부탁하면 미리 받아 줘요.",
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
