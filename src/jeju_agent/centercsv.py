"""센터에서 받은 CSV 알아보기·검수.

센터 CSV 파일 이름은 `Results_날짜_시간.csv`라 이름으로는 어떤 표인지 알 수 없다 (게시판 답변 #24).
헤더로 표 종류를 알아보고, 기간·빠진 달을 확인한다.
값은 PC 안에서만 계산하고 원본 행은 LLM에 보내지 않는다.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field

# 헤더로 알아보는 표 (게시판 #23 답변의 실제 헤더 + 명세서 기준)
KNOWN_TABLES = {
    "tb_card_usage_emd_new": {
        "title": "카드 이용 현황(읍면동)_v02",
        "columns": ["base_year_month", "dstrct_se", "city", "area_type", "bjd", "biz_cd", "biz_nm",
                    "user_type", "tour_type", "age", "sex", "user_cnt", "use_cnt", "use_amt"],
        "export": "불가(원본) · 가공 결과는 심사 후 가능",
    },
}


@dataclass
class Inspected:
    table: str | None
    title: str
    rows: list[dict] = field(default_factory=list)
    months: list[str] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def identify(header: list[str]) -> str | None:
    h = [c.strip().lower() for c in header]
    best, score = None, 0.0
    for key, spec in KNOWN_TABLES.items():
        cols = spec["columns"]
        s = len(set(h) & set(cols)) / len(cols)
        if s > score:
            best, score = key, s
    return best if score >= 0.8 else None


def read_csv_bytes(raw: bytes) -> tuple[list[str], list[dict]]:
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in reader]
    return [c.strip() for c in (reader.fieldnames or [])], rows


def inspect(raw: bytes) -> Inspected:
    header, rows = read_csv_bytes(raw)
    key = identify(header)
    if key is None:
        return Inspected(None, "알 수 없는 표", rows, [], header,
                         ["이 표는 아직 알아보지 못합니다. 헤더를 보고 어떤 표인지 확인이 필요합니다."])
    ins = Inspected(key, KNOWN_TABLES[key]["title"], rows, header=header)
    months = sorted({r.get("base_year_month", "") for r in rows if r.get("base_year_month")})
    ins.months = months
    if not rows:
        ins.problems.append("빈 파일입니다.")
    return ins


def missing_months(months: list[str], month: int, years: list[int]) -> list[str]:
    have = set(months)
    return [f"{y}{month:02d}" for y in years if f"{y}{month:02d}" not in have]


def card_monthly(rows: list[dict], bjd: str | None = None) -> dict[str, dict[str, float]]:
    """카드 표 → ym -> user_type -> 이용금액 합. 'NA'는 0으로 보지 않고 건너뜀."""
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if bjd and r.get("bjd") != bjd:
            continue
        amt = r.get("use_amt", "NA")
        if amt in ("", "NA"):
            continue
        try:
            out[r["base_year_month"]][r.get("user_type", "")] += float(amt)
        except ValueError:
            continue
    return {k: dict(v) for k, v in out.items()}
