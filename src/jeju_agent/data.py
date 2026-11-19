"""허브 스냅샷(월별 집계) 읽기.

스냅샷 파일 (data/snapshot/):
- pop_monthly.csv : emd, ym(YYYYMM), resd, work, visit, days   ← 허브 583 하루값의 월 평균
- foreign_monthly.csv : emd, ym, nationality, visit, days      ← 허브 589 하루값의 월 평균
- meta.json : source("hub"|"dummy"), collected_at, last_ym, note
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field

from . import config


@dataclass
class Snapshot:
    pop: dict = field(default_factory=dict)       # emd -> ym -> {resd, work, visit}
    foreign: dict = field(default_factory=dict)   # emd -> ym -> {nationality: visit}
    meta: dict = field(default_factory=dict)

    @property
    def emds(self) -> list[str]:
        return sorted(set(self.pop) | set(self.foreign))

    @property
    def is_dummy(self) -> bool:
        return self.meta.get("source") != "hub"

    def last_ym(self) -> str:
        yms = [ym for d in self.pop.values() for ym in d]
        return max(yms) if yms else ""


def load_snapshot(directory=None) -> Snapshot:
    d = directory or config.SNAPSHOT_DIR
    snap = Snapshot()
    meta_path = d / "meta.json"
    if meta_path.exists():
        snap.meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pop = defaultdict(dict)
    p = d / "pop_monthly.csv"
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                pop[r["emd"]][r["ym"]] = {k: float(r[k]) for k in ("resd", "work", "visit")}
    fr = defaultdict(lambda: defaultdict(dict))
    p = d / "foreign_monthly.csv"
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                fr[r["emd"]][r["ym"]][r["nationality"]] = float(r["visit"])
    snap.pop = dict(pop)
    snap.foreign = {k: dict(v) for k, v in fr.items()}
    return snap


def series(snap: Snapshot, emd: str, guest: str) -> dict[str, float]:
    """손님 종류별 월 값. guest: foreign | mainland | local"""
    if guest == "foreign":
        return {ym: sum(v.values()) for ym, v in snap.foreign.get(emd, {}).items()}
    rows = snap.pop.get(emd, {})
    if guest == "mainland":
        return {ym: v["visit"] for ym, v in rows.items()}
    if guest == "local":
        return {ym: v["resd"] + v["work"] for ym, v in rows.items()}
    raise ValueError(guest)


def top_nationalities(snap: Snapshot, emd: str, month: int, n: int = 3) -> list[tuple[str, float]]:
    """예년 같은 달 국적별 비중 상위 n."""
    tot = defaultdict(float)
    for ym, v in snap.foreign.get(emd, {}).items():
        if int(ym[4:]) == month:
            for k, x in v.items():
                tot[k] += x
    s = sum(tot.values()) or 1.0
    return [(k, x / s) for k, x in sorted(tot.items(), key=lambda kv: -kv[1])[:n]]
