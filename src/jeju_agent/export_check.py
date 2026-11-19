"""반출 점검: 결과지에 들어갈 표를 센터 반출 기준으로 미리 본다.

기준 (게시판 #12, #43, #50, #51 답변):
- 10 미만 값은 가린다 (비율·1인당 값처럼 계산한 값도 최종값 기준)
- 가린 값이 합계나 다른 칸으로 다시 계산되면 안 된다 (역산)
- 센터 데이터로 낸 결과는 숫자 대신 범주(북적·보통·한산)만 쓴다
최종 판단은 반출 신청 뒤 센터 심사로 정해진다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import config

MASK = "가림"


@dataclass
class CheckResult:
    status: str                      # 안전 | 검토 필요 | 불가
    table: list[list] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def check_table(header: list[str], rows: list[list], total_row: bool = False, from_center: bool = True) -> CheckResult:
    """rows: [[라벨, 값, 값, ...], ...]. 숫자 칸만 검사한다."""
    if not from_center:
        return CheckResult("안전", [header] + rows, ["공개 데이터(제주데이터허브) 값만 들어 있습니다."])
    out = [header]
    notes = []
    masked_cols: dict[int, int] = {}
    for r in rows:
        nr = [r[0]]
        masked_here = 0
        for j, v in enumerate(r[1:], start=1):
            if isinstance(v, (int, float)) and abs(v) < config.MIN_CELL:
                nr.append(MASK)
                masked_here += 1
                masked_cols[j] = masked_cols.get(j, 0) + 1
            else:
                nr.append(v)
        if masked_here == 1 and len(r) > 2:
            notes.append(f"'{r[0]}' 줄에 가린 칸이 하나뿐이라 다른 칸으로 역산될 수 있어 줄 전체를 가렸습니다.")
            nr = [r[0]] + [MASK] * (len(r) - 1)
        out.append(nr)
    if total_row and masked_cols:
        notes.append("합계 줄이 있으면 가린 칸이 역산되므로 합계 줄을 뺐습니다.")
        out = out[:-1]
    status = "안전" if not masked_cols else "검토 필요"
    if masked_cols:
        notes.insert(0, f"10 미만 칸 {sum(masked_cols.values())}개를 가렸습니다.")
    return CheckResult(status, out, notes)


def check_text(text: str, center_numbers: list[float]) -> CheckResult:
    """결과지 문장에 센터 데이터에서 나온 숫자가 그대로 들어갔는지 본다."""
    leaks = [n for n in center_numbers if f"{n:g}" in text]
    if leaks:
        return CheckResult("불가", notes=[f"센터 값 {len(leaks)}개가 문장에 들어 있습니다. 범주로 바꿔야 합니다."])
    return CheckResult("안전", notes=["문장에 센터 원본 숫자가 없습니다."])


def export_memo(emd: str, month: int, used_center: list[str], purpose: str) -> str:
    """반출 신청 설명란·점검 메모 초안 (게시판 #41-3, #47-2 권장 항목)."""
    src = ", ".join(used_center) if used_center else "센터 데이터 없음(제주데이터허브 공개 데이터만)"
    return (
        f"[활용 데이터] {src}; 제주데이터허브 583(읍면동 내국인 유동인구), 589(읍면동 외국인 단기체류 유동인구)\n"
        f"[분석 방법] 손님 신호등 에이전트로 {emd}의 예년 {month}월 값을 1년 평균과 비교(같은 달 평균 ÷ 1년 평균)\n"
        f"[가공 처리] 센터 데이터로 낸 결과는 북적·보통·한산 범주로만 표시, 10 미만 칸 가림, 합계 줄 제거로 역산 방지\n"
        f"[역산 점검] 가린 칸이 한 줄에 하나만 남지 않게 줄 단위로 가림, 합계 미포함\n"
        f"[활용 목적] {purpose}"
    )
