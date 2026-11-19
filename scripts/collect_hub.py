"""제주데이터허브 공개 API(583·589)를 불러 월별 스냅샷을 만든다.

사용: python -I scripts/collect_hub.py [시작YYYYMM] [끝YYYYMM] [읍면동,읍면동...]
- 키: .env 의 JEJU_PROJECT_KEY (허브 로그인 → 프로젝트 → 583·589 담기 → 프로젝트키)
- API는 한 번에 최대 100행(limit=100, number=쪽번호)이라, 달마다 8~14일(요일 7개) 표본만 받는다
- 결과: data/snapshot/pop_monthly.csv, foreign_monthly.csv, meta.json (값 = 표본 7일의 하루 평균)
- 이어받기: data/snapshot/_cache/ 에 달마다 원본 응답을 저장해 두고, 있으면 다시 부르지 않는다
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from jeju_agent import config  # noqa: E402

DATA_IDS = {"583": "pop", "589": "foreign"}
DEFAULT_EMDS = ["정방동", "애월읍", "한림읍", "성산읍", "노형동", "연동"]
SAMPLE_DAYS = (8, 14)
OPENAPI = "https://open.jejudatahub.net/api/proxy/"


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def months(start: str, end: str):
    y, m = int(start[:4]), int(start[4:])
    while f"{y}{m:02d}" <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch_all(data_key: str, key: str, params: dict) -> list[dict]:
    rows, page = [], 1
    while True:
        q = dict(params, limit="100", number=str(page))
        body = get_json(f"{OPENAPI}{data_key}/{key}?" + urllib.parse.urlencode(q))
        rows += body.get("data", [])
        if not body.get("hasMore"):
            return rows
        page += 1
        time.sleep(0.2)


def main() -> None:
    config.load_env()
    key = config.setting("JEJU_PROJECT_KEY")
    if not key:
        sys.exit("JEJU_PROJECT_KEY 가 없습니다. .env 에 허브 프로젝트키를 넣어 주세요.")
    start = sys.argv[1] if len(sys.argv) > 1 else "202201"
    end = sys.argv[2] if len(sys.argv) > 2 else "202608"
    emds = sys.argv[3].split(",") if len(sys.argv) > 3 else DEFAULT_EMDS
    out = config.SNAPSHOT_DIR
    cache = out / "_cache"
    cache.mkdir(parents=True, exist_ok=True)
    keys = {i: get_json(f"https://jejudatahub.net/api/data/view?id={i}")["dataKey"] for i in DATA_IDS}

    pop = defaultdict(lambda: defaultdict(float))       # (emd, ym) -> col -> sum
    pop_days = defaultdict(set)
    fr = defaultdict(lambda: defaultdict(float))        # (emd, ym) -> nat -> sum
    fr_days = defaultdict(set)
    calls = 0
    for emd in emds:
        for y, m in months(start, end):
            ym = f"{y}{m:02d}"
            for did in DATA_IDS:
                cf = cache / f"{did}_{emd}_{ym}.json"
                if cf.exists():
                    rows = json.loads(cf.read_text(encoding="utf-8"))
                else:
                    params = {"startDate": f"{ym}{SAMPLE_DAYS[0]:02d}", "endDate": f"{ym}{SAMPLE_DAYS[1]:02d}", "emd": emd}
                    try:
                        rows = fetch_all(keys[did], key, params)
                    except Exception as e:  # noqa: BLE001
                        print(f"! {did} {emd} {ym}: {e}", flush=True)
                        continue
                    calls += 1
                    cf.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
                for r in rows:
                    if did == "583":
                        for c in ("resdPop", "workPop", "visitPop"):
                            pop[(emd, ym)][c] += float(r.get(c) or 0)
                        pop_days[(emd, ym)].add(r["baseDate"])
                    else:
                        fr[(emd, ym)][r["nationality"]] += float(r.get("visitPop") or 0)
                        fr_days[(emd, ym)].add(r["baseDate"])
            print(f"{emd} {ym} ok (calls {calls})", flush=True)

    with (out / "pop_monthly.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["emd", "ym", "resd", "work", "visit", "days"])
        for (emd, ym), v in sorted(pop.items()):
            n = len(pop_days[(emd, ym)])
            if n:
                w.writerow([emd, ym, round(v["resdPop"] / n, 1), round(v["workPop"] / n, 1), round(v["visitPop"] / n, 1), n])
    with (out / "foreign_monthly.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["emd", "ym", "nationality", "visit", "days"])
        for (emd, ym), v in sorted(fr.items()):
            n = len(fr_days[(emd, ym)])
            for nat, s in sorted(v.items()):
                if n:
                    w.writerow([emd, ym, nat, round(s / n, 1), n])
    (out / "meta.json").write_text(json.dumps({
        "source": "hub",
        "collected_at": date.today().isoformat(),
        "range": [start, end],
        "emds": emds,
        "sample": f"달마다 {SAMPLE_DAYS[0]}~{SAMPLE_DAYS[1]}일 7일 표본의 하루 평균",
        "datasets": {"583": "읍면동 단위 내국인 유동인구 (제주데이터허브, API)",
                     "589": "읍면동 단위 외국인 단기체류 유동인구 (제주데이터허브, API)"},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", calls, "calls")


if __name__ == "__main__":
    main()
