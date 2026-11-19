"""대화 속 카드: 에이전트(Claude)가 질문 의도에 맞게 블록을 골라 조립하고, 숫자는 이 모듈이 채운다.

Claude는 "어떤 손님의 어느 달을 어떤 모양(신호·막대·선·국적…)으로 보여 줄지"만 정한다.
배율·신호·국적 비중은 signals·data 계산 결과로만 채우므로 Claude가 숫자를 지어낼 수 없다.
글로 쓰는 블록(할 일·칩·짧은 글)에 계산에 없는 배율이 들어가면 그 항목을 뺀다.
"""
from __future__ import annotations

import re
import statistics

from . import data, signals
from .signals import GUEST_NAME, LABEL

GUESTS = ("foreign", "mainland", "local")
GUEST_KO = {"외국인": "foreign", "육지": "mainland", "동네": "local"}
BLOCK_TYPES = ("signals", "bar", "line", "nations", "actions", "chips", "text", "order")
MAX_BLOCKS = 5


# ---------- 1년 흐름 ----------
def year_overview(snap: data.Snapshot, emd: str) -> dict:
    """1~12월 세 손님 신호. 조용한 달·붐비는 달은 세 손님 배율 평균으로 고른다."""
    grid = {g: [signals.compute(data.series(snap, emd, g), g, m) for m in range(1, 13)] for g in GUESTS}
    score = {}
    for m in range(1, 13):
        rs = [grid[g][m - 1].ratio for g in GUESTS if grid[g][m - 1].ratio is not None]
        if rs:
            score[m] = statistics.fmean(rs)
    order = sorted(score, key=score.get)
    return {
        "emd": emd,
        "grid": {g: [{"month": s.month, "level": s.level, "ratio": s.ratio} for s in grid[g]] for g in GUESTS},
        "quiet": order[:3],
        "busy": order[::-1][:3],
    }


def year_for_llm(y: dict) -> dict:
    """LLM에 넘길 1년 흐름 (공개 데이터 배율만)."""
    by_month = {}
    for m in range(1, 13):
        row = {}
        for g in GUESTS:
            c = y["grid"][g][m - 1]
            row[GUEST_NAME[g]] = f"{LABEL[c['level']]} {c['ratio']:.1f}배" if c["ratio"] is not None else "보류"
        by_month[f"{m}월"] = row
    return {"읍면동": y["emd"], "월별": by_month,
            "조용한달": [f"{m}월" for m in y["quiet"]], "붐비는달": [f"{m}월" for m in y["busy"]]}


# ---------- 카드 조립 ----------
def _guest(x) -> str | None:
    if x in GUESTS:
        return x
    for k, v in GUEST_KO.items():
        if isinstance(x, str) and k in x:
            return v
    return None


def _months(xs, default=None) -> list[int]:
    out = []
    for x in xs or []:
        try:
            m = int(str(x).replace("월", ""))
        except ValueError:
            continue
        if 1 <= m <= 12 and m not in out:
            out.append(m)
    return out or list(default or [])


def allowed_numbers(y: dict) -> set[str]:
    """글에 써도 되는 배율 (계산 결과에 있는 것만)."""
    return {f"{c['ratio']:.1f}" for g in GUESTS for c in y["grid"][g] if c["ratio"] is not None}


def _clean(text: str, allowed: set[str]) -> str | None:
    """계산에 없는 '0.0배'가 들어 있으면 버린다."""
    text = str(text or "").strip()
    for n in re.findall(r"(\d+(?:\.\d+)?)\s*배", text):
        if f"{float(n):.1f}" not in allowed:
            return None
    return text or None


def build(snap: data.Snapshot, spec: dict, order_fn=None) -> dict | None:
    """Claude가 고른 카드 설계(spec)를 실제 값으로 채운다. 잘못된 블록은 조용히 뺀다."""
    emd = spec.get("emd")
    if emd not in snap.emds:
        return None
    y = year_overview(snap, emd)
    allowed = allowed_numbers(y)
    cell = lambda g, m: y["grid"][g][m - 1]
    blocks = []
    for b in (spec.get("blocks") or [])[:MAX_BLOCKS]:
        t = b.get("type")
        if t not in BLOCK_TYPES:
            continue
        title = _clean(b.get("title", ""), allowed) or ""
        if t == "signals":
            items = []
            for it in b.get("items") or []:
                g, m = _guest(it.get("guest")), _months([it.get("month")])
                if g and m:
                    c = cell(g, m[0])
                    items.append({"guest": g, "name": GUEST_NAME[g], "month": m[0], "level": c["level"],
                                  "label": LABEL[c["level"]], "ratio": c["ratio"]})
            if items:
                blocks.append({"type": t, "title": title, "items": items[:6]})
        elif t == "bar":
            g = _guest(b.get("guest"))
            if g:
                ms = _months(b.get("months"), range(1, 13))
                blocks.append({"type": t, "title": title or f"{GUEST_NAME[g]} 달별 흐름", "guest": g,
                               "points": [{"month": m, **{k: cell(g, m)[k] for k in ("level", "ratio")}} for m in ms],
                               "highlight": _months(b.get("highlight"))})
        elif t == "line":
            gs = [g for g in (_guest(x) for x in b.get("guests") or GUESTS) if g] or list(GUESTS)
            ms = _months(b.get("months"), range(1, 13))
            blocks.append({"type": t, "title": title or "1년 손님 흐름", "months": ms,
                           "series": [{"guest": g, "name": GUEST_NAME[g], "points": [cell(g, m)["ratio"] for m in ms]} for g in dict.fromkeys(gs)],
                           "highlight": _months(b.get("highlight"))})
        elif t == "nations":
            m = _months([b.get("month")])
            if m:
                ns = data.top_nationalities(snap, emd, m[0])
                if ns:
                    blocks.append({"type": t, "title": title or f"{m[0]}월 외국인 손님 국적",
                                   "items": [{"name": n, "share": round(p, 3)} for n, p in ns]})
        elif t == "actions":
            items = []
            for it in b.get("items") or []:
                tt, dd = _clean(it.get("title"), allowed), _clean(it.get("detail", ""), allowed)
                if tt:
                    items.append({"title": tt, "detail": dd or ""})
            if items:
                blocks.append({"type": t, "title": title or "이렇게 준비해 보세요", "items": items[:4]})
        elif t == "chips":
            items = [x for x in (_clean(i, allowed) for i in b.get("items") or []) if x]
            if items:
                blocks.append({"type": t, "title": title, "items": items[:8], "tone": b.get("tone") if b.get("tone") in ("busy", "calm", "mid") else "mid"})
        elif t == "text":
            tx = _clean(b.get("text"), allowed)
            if tx:
                blocks.append({"type": t, "text": tx})
        elif t == "order" and order_fn:
            m = _months([b.get("month")])
            if m:
                blocks.append({"type": t, **order_fn(snap, emd, m[0])})
    if not blocks:
        return None
    return {"emd": emd, "title": _clean(spec.get("title"), allowed) or emd, "subtitle": _clean(spec.get("subtitle", ""), allowed) or "",
            "blocks": blocks}


# ---------- AI 없이 쓰는 기본 카드 ----------
def month_spec(rep: dict) -> dict:
    blocks = [{"type": "signals", "items": [{"guest": s["guest"], "month": rep["month"]} for s in rep["signals"]]}]
    if rep["actions"]:
        blocks.append({"type": "actions", "items": [{"title": a["title"], "detail": a["detail"]} for a in rep["actions"]]})
    if any(s["guest"] == "foreign" and s["level"] == "busy" for s in rep["signals"]):
        blocks.append({"type": "nations", "month": rep["month"]})
    blocks += [{"type": "text", "text": a} for a in rep.get("asks", [])][:MAX_BLOCKS - len(blocks)]
    return {"emd": rep["emd"], "title": f"{rep['month']}월 {rep['emd']} 손님", "subtitle": "예년 같은 달을 1년 평균과 견줬어요",
            "blocks": blocks}


def year_spec(y: dict) -> dict:
    return {"emd": y["emd"], "title": f"{y['emd']} 1년 손님 흐름", "subtitle": "1.0이 1년 평균이에요",
            "blocks": [{"type": "line", "highlight": y["quiet"][:2]},
                       {"type": "chips", "title": "조용했던 달", "items": [f"{m}월" for m in y["quiet"]], "tone": "calm"},
                       {"type": "chips", "title": "붐볐던 달", "items": [f"{m}월" for m in y["busy"]], "tone": "busy"}]}


def year_sentences(y: dict, busy_first: bool = False) -> list[str]:
    q = ", ".join(f"{m}월" for m in y["quiet"][:2])
    b = ", ".join(f"{m}월" for m in y["busy"][:2])
    if busy_first:
        return [f"{y['emd']}은 예년에 {b}이 가장 붐볐어요.", f"그때는 알바와 재료를 넉넉히 챙겨 보세요. 가장 조용했던 달은 {q}이에요."]
    return [f"{y['emd']}은 예년에 {q}이 가장 조용했어요.", f"쉬려면 {y['quiet'][0]}월을 먼저 생각해 보세요. 가장 붐볐던 달은 {b}이에요."]
