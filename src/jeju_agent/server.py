"""센터 PC에서 도는 로컬 서버 + 브라우저 화면.

실행: python -m jeju_agent.server   (start.bat 이 대신 실행)
주소: http://127.0.0.1:8765  (이 PC 안에서만 열림)
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import cards, agent, centercsv, config, data, llm, report

PORT = 8765  # .env 의 PORT 로 바꿀 수 있음
STATE: dict = {}


def session() -> agent.Session:
    if "s" not in STATE:
        STATE["s"] = agent.Session(data.load_snapshot())
    return STATE["s"]


def clear_work() -> None:
    if config.WORK_DIR.exists():
        shutil.rmtree(config.WORK_DIR, ignore_errors=True)
    STATE.pop("s", None)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 조용히
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._send(200, (config.WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/info":
            s = session()
            return self._json({"emds": s.snap.emds, "data_until": s.snap.last_ym(), "dummy": s.snap.is_dummy,
                               "llm": llm.available(), "auto_delete": config.auto_delete(),
                               "uploads": [{"title": x.title, "months": x.months} for x in s.uploads]})
        if u.path == "/api/report":
            q = parse_qs(u.query)
            s = session()
            emd, month = q.get("emd", [""])[0], int(q.get("month", ["1"])[0])
            if emd not in s.snap.emds:
                return self._json({"error": "아직 볼 수 없는 동네예요."}, 400)
            s.report = report.build(s.snap, emd, month, s.uploads)
            sentences = report.template_sentences(s.report)
            card = cards.build(s.snap, cards.month_spec(s.report))
            return self._json({"report": s.report, "sentences": sentences, "card": card})
        if u.path == "/api/order":
            q = parse_qs(u.query)
            return self._json(agent.order(session().snap, q.get("emd", [""])[0], int(q.get("month", ["1"])[0])))
        if u.path == "/api/llmlog":
            p = config.WORK_DIR / "llm_log.jsonl"
            return self._send(200, p.read_bytes() if p.exists() else b"", "text/plain; charset=utf-8")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        if u.path == "/api/ask":
            text = json.loads(raw.decode("utf-8")).get("text", "")
            return self._json(session().ask(text))
        if u.path == "/api/upload":
            # 센터에서 받은 CSV. work/ 에만 두고 퇴실 때 지운다.
            name = parse_qs(u.query).get("name", ["upload.csv"])[0]
            config.WORK_DIR.mkdir(parents=True, exist_ok=True)
            (config.WORK_DIR / ("in_" + "".join(c for c in name if c.isalnum() or c in "._-"))).write_bytes(raw)
            ins = centercsv.inspect(raw)
            session().uploads.append(ins)
            return self._json({"title": ins.title, "table": ins.table, "months": ins.months, "problems": ins.problems,
                               "rows": len(ins.rows)})
        if u.path == "/api/newchat":
            # 새 화면 = 새 대화. 넣은 센터 파일은 그대로 둔다
            s = session()
            s.messages, s.report, s.card = [], None, None
            return self._json({"ok": True})
        if u.path == "/api/clear":
            clear_work()
            return self._json({"ok": True})
        self._send(404, b"not found", "text/plain")


def main() -> None:
    config.load_env()
    if config.auto_delete():
        clear_work()   # 지난 이용자 자료 지우기
    port = int(config.setting("PORT", str(PORT)))
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        sys.exit(f"{port} 번 포트를 이미 쓰고 있습니다. 켜져 있는 손님 신호등 창을 닫거나 .env 에 PORT=8766 처럼 다른 번호를 넣으세요.")
    url = f"http://127.0.0.1:{port}"
    print(f"손님 신호등이 켜졌습니다: {url}  (끄려면 이 창을 닫으세요)", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
