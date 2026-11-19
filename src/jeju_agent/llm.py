"""Claude API 호출 (Messages API, 표준 라이브러리 urllib).

공식 SDK 대신 HTTP를 직접 부르는 이유: 센터 PC는 디지털 서명이 없는 확장 모듈(.pyd)을 막을 수 있는데
(대회 게시판 #49·#57·#59), SDK가 쓰는 pydantic-core 등이 그런 확장 모듈이다. 표준 라이브러리만 쓰면
설치도 Python 하나로 끝난다.

LLM으로 가는 내용은 work/llm_log.jsonl 에 남겨 담당자가 확인할 수 있다.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from . import config

API_URL = "https://api.anthropic.com/v1/messages"


class LLMUnavailable(Exception):
    pass


def available() -> bool:
    return bool(config.setting("ANTHROPIC_API_KEY")) and config.setting("LLM", "on").lower() != "off"


def scrub(text: str) -> str:
    """사장님이 쓴 문장에서 긴 숫자(매출·건수 등)를 가린다. 센터 값이 섞여 나가지 않게."""
    return re.sub(r"\d[\d,\.]{2,}", "○", text)


def _log(payload: dict) -> None:
    try:
        config.WORK_DIR.mkdir(parents=True, exist_ok=True)
        with (config.WORK_DIR / "llm_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "messages": payload.get("messages")},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def create(system: str, messages: list, tools: list | None = None, max_tokens: int = 4000) -> dict:
    key = config.setting("ANTHROPIC_API_KEY")
    if not key:
        raise LLMUnavailable("ANTHROPIC_API_KEY 없음")
    body = {
        "model": config.setting("LLM_MODEL", "claude-opus-5-5"),
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "output_config": {"effort": config.setting("LLM_EFFORT", "low")},
        "fallbacks": "default",
    }
    if tools:
        body["tools"] = tools
    _log(body)
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "server-side-fallback-2026-07-01",
        },
        method="POST",
    )
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            if e.code in (429, 500, 502, 503, 529):
                time.sleep(2 * (attempt + 1))
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"연결 실패: {e}"
            time.sleep(2 * (attempt + 1))
    raise LLMUnavailable(last or "알 수 없는 오류")
