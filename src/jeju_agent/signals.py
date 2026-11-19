"""신호 계산: 예년 같은 달 평균 ÷ 1년 평균 → 북적·보통·한산.

숫자는 이 모듈이 낸다. LLM은 숫자를 만들지 않는다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, asdict

from . import config

LABEL = {"busy": "북적", "mid": "보통", "calm": "한산", "hold": "보류"}
GUEST_NAME = {"foreign": "외국인 손님", "mainland": "육지 손님", "local": "동네 손님"}


@dataclass
class Signal:
    guest: str
    month: int
    level: str          # busy | mid | calm | hold
    ratio: float | None
    years: list[int]
    reason: str = ""

    @property
    def label(self) -> str:
        return LABEL[self.level]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label
        d["guest_name"] = GUEST_NAME[self.guest]
        return d


def _usable_years(series: dict[str, float], month: int, from_year: int = 0) -> list[int]:
    """그 달 값이 있고 10달 이상 있는 해만 쓴다 (허브 589는 2025년 4·5월이 비어 있음)."""
    by_year: dict[int, set] = {}
    for ym in series:
        by_year.setdefault(int(ym[:4]), set()).add(int(ym[4:]))
    return sorted(y for y, ms in by_year.items()
                  if y >= from_year and len(ms) >= config.MIN_MONTHS and month in ms)


def _year_vals(series: dict[str, float], y: int) -> list[float]:
    return [series[f"{y}{m:02d}"] for m in range(1, 13) if f"{y}{m:02d}" in series]


def ratio_a(series: dict[str, float], month: int, years: list[int]) -> float:
    """방법 A: 해마다 (그 달 ÷ 그 해 월평균)을 구해 평균."""
    rs = [series[f"{y}{month:02d}"] / statistics.fmean(_year_vals(series, y)) for y in years]
    return statistics.fmean(rs)


def ratio_b(series: dict[str, float], month: int, years: list[int]) -> float:
    """방법 B: 같은 계산을 합계·개수로 따로 한 번 더 (다른 코드 경로로 재확인)."""
    total = 0.0
    for y in years:
        year_sum, n = 0.0, 0
        for m in range(1, 13):
            v = series.get(f"{y}{m:02d}")
            if v is not None:
                year_sum += v
                n += 1
        total += series[f"{y}{month:02d}"] * n / year_sum
    return total / len(years)


def level_of(ratio: float) -> str:
    if ratio >= config.BUSY_AT:
        return "busy"
    if ratio <= config.CALM_AT:
        return "calm"
    return "mid"


def compute(series: dict[str, float], guest: str, month: int) -> Signal:
    years = _usable_years(series, month, config.FROM_YEAR)
    if len(years) < config.MIN_YEARS:
        return Signal(guest, month, "hold", None, years,
                      "기록이 부족해서 아직 판단하기 어려워요.")
    a = ratio_a(series, month, years)
    b = ratio_b(series, month, years)
    if abs(a - b) > config.RECHECK_TOL * max(abs(a), 1e-9):
        return Signal(guest, month, "hold", None, years, "계산을 다시 확인하는 중이에요.")
    return Signal(guest, month, level_of(a), round(a, 2), years)
