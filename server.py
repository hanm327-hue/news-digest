"""digest 폴더의 다이제스트 파일을 보여 주는 로컬 서버.

    python server.py            # http://127.0.0.1:8000
    python server.py 8080       # 포트 지정

- /                 정적 페이지 (web/index.html)
- /api/list         digest/*.md 목록 (JSON, 최신순)
- /digest/<파일>.md  다이제스트 원본 (YYYY-MM-DD.md 형식만 허용)

이 PC 안에서만 접속되도록 127.0.0.1에만 바인딩한다.
digest 폴더와 web 폴더 밖의 파일은 내보내지 않는다.
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE = Path(__file__).resolve().parent
DIGEST = BASE / "digest"
WEB = BASE / "web"
NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)

        if path in ("/", "/index.html"):
            return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")

        if path in ("/api/list", "/digest/index.json"):
            files = []
            if DIGEST.is_dir():
                for f in sorted(DIGEST.glob("*.md"), reverse=True):
                    if NAME_RE.match(f.name):
                        files.append({"name": f.name, "size": f.stat().st_size})
            body = json.dumps(files, ensure_ascii=False).encode("utf-8")
            return self._send(200, body, "application/json; charset=utf-8")

        if path.startswith("/digest/"):
            name = path[len("/digest/"):]
            f = DIGEST / name
            if NAME_RE.match(name) and f.is_file():
                return self._send(200, f.read_bytes(), "text/markdown; charset=utf-8")

        self._send(404, "없는 페이지예요.".encode("utf-8"), "text/plain; charset=utf-8")

    def log_message(self, fmt, *args) -> None:
        sys.stderr.write("[server] " + fmt % args + "\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"다이제스트 서버 실행 중: http://127.0.0.1:{port}  (종료: Ctrl+C)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
