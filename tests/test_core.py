"""핵심 계산 시험. 실행: python -m unittest discover -s tests (PYTHONPATH=src)"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jeju_agent import agent, centercsv, data, export_check, report, signals  # noqa: E402


def seasonal(years=(2023, 2024, 2025, 2026), jan=50.0, aug=150.0):
    s = {}
    for y in years:
        for m in range(1, 13):
            s[f"{y}{m:02d}"] = jan if m == 1 else aug if m == 8 else 100.0
    return s


class SignalTest(unittest.TestCase):
    def test_levels(self):
        s = seasonal()
        self.assertEqual(signals.compute(s, "mainland", 1).level, "calm")
        self.assertEqual(signals.compute(s, "mainland", 8).level, "busy")
        self.assertEqual(signals.compute(s, "mainland", 5).level, "mid")

    def test_two_methods_agree(self):
        s = seasonal()
        yrs = [2023, 2024, 2025, 2026]
        self.assertAlmostEqual(signals.ratio_a(s, 1, yrs), signals.ratio_b(s, 1, yrs), places=9)

    def test_hold_when_few_years(self):
        sig = signals.compute(seasonal(years=(2024, 2025)), "local", 1)
        self.assertEqual(sig.level, "hold")
        self.assertIsNone(sig.ratio)

    def test_incomplete_year_skipped(self):
        s = seasonal()
        s.update({"202701": 10.0, "202702": 10.0})   # 2027은 10달이 안 돼 빠짐
        self.assertEqual(signals.compute(s, "mainland", 1).years, [2023, 2024, 2025, 2026])

    def test_year_with_two_gaps_used(self):
        s = seasonal()
        del s["202504"], s["202505"]                  # 허브 589처럼 두 달 비어도 씀
        self.assertEqual(signals.compute(s, "mainland", 1).years, [2023, 2024, 2025, 2026])
        yrs = [2023, 2024, 2025, 2026]
        self.assertAlmostEqual(signals.ratio_a(s, 1, yrs), signals.ratio_b(s, 1, yrs), places=9)

    def test_skips_2022(self):
        s = seasonal(years=(2022, 2023, 2024, 2025))
        self.assertEqual(signals.compute(s, "foreign", 1).years, [2023, 2024, 2025])


class ExportTest(unittest.TestCase):
    def test_mask_and_inverse(self):
        r = export_check.check_table(["업종", "1월", "2월"], [["한식", 120, 5], ["카페", 30, 40]])
        self.assertEqual(r.status, "검토 필요")
        self.assertEqual(r.table[1], ["한식", "가림", "가림"])   # 한 줄에 하나만 가리면 역산되므로 줄 전체
        self.assertEqual(r.table[2], ["카페", 30, 40])

    def test_public_only_safe(self):
        self.assertEqual(export_check.check_table(["a"], [["x", 1]], from_center=False).status, "안전")


class CsvTest(unittest.TestCase):
    def test_identify_card(self):
        raw = ('"base_year_month","dstrct_se","city","area_type","bjd","biz_cd","biz_nm","user_type","tour_type","age","sex","user_cnt","use_cnt","use_amt"\n'
               '"202501","서귀포시 서부","서귀포시","읍면","대정읍","I56111","한식 음식점업","내국인","단체","60","여성","4","1","1000000"\n').encode()
        ins = centercsv.inspect(raw)
        self.assertEqual(ins.table, "tb_card_usage_emd_new")
        self.assertEqual(ins.months, ["202501"])
        self.assertEqual(centercsv.missing_months(ins.months, 1, [2024, 2025]), ["202401"])


class AgentRulesTest(unittest.TestCase):
    def setUp(self):
        snap = data.Snapshot(meta={"source": "dummy"})
        snap.pop = {"애월읍": {ym: {"resd": 100.0, "work": 10.0, "visit": v} for ym, v in seasonal().items()}}
        snap.foreign = {"애월읍": {ym: {"중국": v, "일본": 10.0} for ym, v in seasonal().items()}}
        self.s = agent.Session(snap)

    def test_month_parse(self):
        self.assertEqual(agent.parse_month("1월에 쉬어도 돼요?"), 1)
        self.assertEqual(agent.parse_month("겨울에"), 1)

    def test_out_of_scope(self):
        self.assertIsNotNone(agent.out_of_scope("다음 달 매출 얼마 나와요?"))

    def test_rules_flow(self):
        r = self.s._ask_rules("애월읍 1월에 쉬어도 될까요?")
        self.assertEqual(r["report"]["emd"], "애월읍")
        levels = {x["guest"]: x["level"] for x in r["report"]["signals"]}
        self.assertEqual(levels["mainland"], "calm")
        self.assertTrue(any(a["title"].startswith("쉬거나") for a in r["report"]["actions"]))

    def test_llm_summary_has_no_center_rows(self):
        rep = report.build(self.s.snap, "애월읍", 8)
        summ = report.summary_for_llm(rep)
        self.assertNotIn("rows", str(summ))


if __name__ == "__main__":
    unittest.main()


class AgentLoopTest(unittest.TestCase):
    """LLM 응답을 흉내 내 도구 호출 순환이 도는지 본다 (실제 API 호출 없음)."""

    def test_tool_loop(self):
        from jeju_agent import llm
        snap = data.Snapshot(meta={"source": "dummy"})
        snap.pop = {"애월읍": {ym: {"resd": 100.0, "work": 10.0, "visit": v} for ym, v in seasonal().items()}}
        snap.foreign = {"애월읍": {ym: {"중국": v} for ym, v in seasonal().items()}}
        s = agent.Session(snap)
        replies = [
            {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "t1", "name": "make_report", "input": {"emd": "애월읍", "month": 1}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": "1월은 육지 손님이 한산합니다."}]},
        ]
        sent = []
        orig_create, orig_avail = llm.create, llm.available
        llm.create = lambda system, messages, tools=None, max_tokens=4000: (sent.append(list(messages)), replies.pop(0))[1]
        llm.available = lambda: True
        try:
            r = s.ask("애월 1월 매출 1,200,000원인데 쉬어도 돼요?")
        finally:
            llm.create, llm.available = orig_create, orig_avail
        self.assertEqual(r["answer"], "1월은 육지 손님이 한산합니다.")
        self.assertEqual([t["tool"] for t in r["trace"]], ["make_report"])
        self.assertEqual(r["report"]["emd"], "애월읍")
        self.assertNotIn("1,200,000", sent[0][0]["content"])          # 긴 숫자는 가려서 보냄
        tool_result = sent[1][-1]["content"][0]
        self.assertEqual(tool_result["type"], "tool_result")
        self.assertIn("한산", tool_result["content"])
