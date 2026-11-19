"""결과지(A4 한 장) 조립: 신호 셋 → 할 일 셋 → 근거·한계 → 반출 점검."""
from __future__ import annotations

from . import centercsv, data, export_check, rules, signals
from .signals import GUEST_NAME

DATASET = {"foreign": "허브 589", "mainland": "허브 583 방문 인구", "local": "허브 583 거주·근무 인구"}
NOTE = "지난 기록을 본 거예요. 올해를 예측한 건 아니에요."
# 자세한 한계는 RESULTS.md·DATA_SPEC.md 에 둔다 (화면에는 한 줄만)
SAY = {"busy": "평소보다 많아요", "mid": "평소와 비슷해요", "calm": "평소보다 적어요", "hold": "아직 알기 어려워요"}


def build(snap: data.Snapshot, emd: str, month: int, uploads: list[centercsv.Inspected] | None = None,
          purpose: str = "가게 운영 준비(휴무·발주·메뉴판) 참고") -> dict:
    sigs = [signals.compute(data.series(snap, emd, g), g, month) for g in ("foreign", "mainland", "local")]
    actions, evidence = [], []
    for s in sigs:
        a = rules.action_for(s.guest, s.level)
        if s.level == "hold":
            evidence.append(f"{GUEST_NAME[s.guest]}: {s.reason}")
            continue
        why = f"{GUEST_NAME[s.guest]}이 평소의 {s.ratio:.1f}배였어요 · {DATASET[s.guest]}"
        actions.append({"guest": s.guest, "title": a[0], "detail": a[1], "why": why})
        evidence.append(why)

    nations = data.top_nationalities(snap, emd, month)
    foreign_sig = sigs[0]
    if foreign_sig.level == "busy" and nations:
        top = nations[0][0]
        pay = rules.PAY_BY_NATION.get(top)
        if pay and actions:
            actions[0]["detail"] = f"{top} 손님이 가장 많아요({nations[0][1]:.0%}). {pay}를 챙겨 두면 좋아요."

    # 센터 CSV (반출 불가 원본): PC 안에서만 계산, 결과는 범주만
    center_lines, used_center, asks = [], [], []
    by_table: dict[str, set] = {}
    titles: dict[str, str] = {}
    for ins in uploads or []:
        if ins.table is None:
            asks.append("이 파일은 어떤 표인지 모르겠어요. 센터 화면에서 받은 표 이름을 알려 주세요.")
            continue
        by_table.setdefault(ins.table, set()).update(ins.months)
        titles[ins.table] = ins.title
    for table, months_set in by_table.items():
        title = titles[table]
        used_center.append(title)
        months = sorted(months_set)
        years = sorted({int(m[:4]) for m in months if int(m[4:]) == month})
        miss = centercsv.missing_months(months, month, list(range(min(years), max(years) + 1))) if years else [f"최근 3년의 {month}월"]
        if miss:
            asks.append(f"{', '.join(m if not m[:4].isdigit() else m[:4] + '년 ' + str(int(m[4:])) + '월' for m in miss)} 자료가 빠졌어요. 센터 화면에서 받아 주실래요?")
        center_lines.append(f"센터 {title} {len(months)}개월치를 확인했어요.")

    check = export_check.check_table(
        ["손님", "신호"], [[GUEST_NAME[s.guest], s.label] for s in sigs], from_center=bool(used_center))
    memo = export_check.export_memo(emd, month, used_center, purpose)

    return {
        "emd": emd,
        "month": month,
        "data_until": snap.last_ym(),
        "dummy": snap.is_dummy,
        "signals": [s.to_dict() for s in sigs],
        "actions": actions,
        "nations": [{"name": n, "share": round(p, 3)} for n, p in nations],
        "evidence": evidence,
        "center": center_lines,
        "asks": asks,
        "note": NOTE,
        "export": {"status": check.status, "notes": check.notes, "memo": memo},
    }


def summary_for_llm(rep: dict) -> dict:
    """LLM에 넘길 내용: 범주 이름·할 일·공개 데이터 배율만. 센터 원본 값은 넣지 않는다."""
    return {
        "읍면동": rep["emd"], "월": rep["month"], "기록": rep["data_until"],
        "신호": {s["guest_name"]: s["label"] for s in rep["signals"]},
        "할일": [a["title"] for a in rep["actions"]],
        "근거": rep["evidence"],
        "국적상위": [n["name"] for n in rep["nations"]],
        "되물을것": rep["asks"],
    }


SHORT = {"foreign": "외국인", "mainland": "육지", "local": "동네"}
MID_FORM = {"busy": "평소보다 많고", "mid": "평소와 비슷하고", "calm": "평소보다 적고", "hold": "아직 알기 어렵고"}


def template_sentences(rep: dict) -> list[str]:
    """LLM 없이 쓰는 틀 문장 (LLM이 꺼져 있거나 센터 보안으로 막힐 때)."""
    groups: dict[str, list[str]] = {}
    for x in rep["signals"]:
        groups.setdefault(x["level"], []).append(SHORT[x["guest"]])
    hold = groups.pop("hold", [])
    parts = list(groups.items())
    phrases = [f"{'·'.join(names)} 손님이 {(SAY if i == len(parts) - 1 else MID_FORM)[lvl]}"
               for i, (lvl, names) in enumerate(parts)]
    out = [f"{rep['month']}월 {rep['emd']}에는 " + ", ".join(phrases) + "."] if phrases else []
    if hold:
        out.append(f"{'·'.join(hold)} 손님은 기록이 부족해서 아직 알기 어려워요.")
    if rep["actions"]:
        t = rep["actions"][0]["title"]
        out.append(t + "." if t.endswith("요") else f"{t}부터 해 보세요.")
    return out
