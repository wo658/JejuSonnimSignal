"""RESULTS.md 의 실행 결과 표를 스냅샷으로 다시 만든다. 사용: PYTHONPATH=src python -I scripts/results_table.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jeju_agent import data, report  # noqa: E402

snap = data.load_snapshot()
print(f"기록: {snap.last_ym()[:4]}년 {int(snap.last_ym()[4:])}월까지 · 출처 {snap.meta.get('source')} · {snap.meta.get('sample', '')}\n")
print("| 읍면동 | 달 | 외국인 | 육지 | 동네 | 할 일 (규칙표) |")
print("|---|---|---|---|---|---|")
for emd in snap.emds:
    for m in (1, 8):
        r = report.build(snap, emd, m)
        cells = []
        for s in r["signals"]:
            cells.append(f"{s['label']} ({s['ratio']:.2f})" if s["ratio"] is not None else s["label"])
        print(f"| {emd} | {m}월 | " + " | ".join(cells) + " | " + ", ".join(a["title"] for a in r["actions"]) + " |")
