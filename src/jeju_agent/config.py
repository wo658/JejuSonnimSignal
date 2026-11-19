"""경로와 설정. 외부 패키지 없이 표준 라이브러리만 쓴다 (센터 PC는 서명 없는 확장 모듈을 막을 수 있음)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = ROOT / "data" / "snapshot"   # 허브 공개 API를 미리 받아 둔 집계 파일
WORK_DIR = ROOT / "work"                     # 이용자가 넣은 CSV, 만든 결과지 (지우기 대상)
WEB_DIR = Path(__file__).resolve().parent / "web"

# 신호 경계값 (설정값. 시범 운영에서 조정)
BUSY_AT = 1.15
CALM_AT = 0.85
MIN_YEARS = 3          # 비교할 해가 이보다 적으면 판단 보류
MIN_MONTHS = 10        # 한 해에 이만큼 달이 있어야 그 해를 씀
FROM_YEAR = 2023       # 2022년은 뺌: 583은 2022년 7월 앞뒤로 값이 절반으로 끊기고, 589는 코로나 뒤 회복기
RECHECK_TOL = 0.001    # 두 방법 결과 차이 허용치 (0.1%)
MIN_CELL = 10          # 반출 점검: 10 미만 칸은 가림


def load_env(path: Path | None = None) -> None:
    """.env 파일을 읽어 환경변수로 넣는다 (이미 있는 값은 덮어쓰지 않음)."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def auto_delete() -> bool:
    """퇴실 때 지우기 기본값. AUTO_DELETE=off 로 끈다."""
    return setting("AUTO_DELETE", "on").lower() not in ("off", "0", "false", "no")
