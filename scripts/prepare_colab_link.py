"""Generate a local clickable connection page without printing its token."""

import html
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "artifacts/colab"
url = json.loads((root / "connection.json").read_text(encoding="utf-8"))["url"]
if not url.startswith("https://colab.research.google.com/notebooks/empty.ipynb#"):
    raise SystemExit("Unexpected connection URL")
(root / "connect.html").write_text(
    '<!doctype html><meta charset="utf-8"><title>Nhóm 13 — Colab MCP</title>'
    "<h1>Kết nối Colab MCP</h1><p>Liên kết chỉ dùng trên máy này, cho phiên MCP hiện tại.</p>"
    f'<p><a href="{html.escape(url, quote=True)}">Mở Colab và kết nối MCP</a></p>',
    encoding="utf-8",
)
(root / "connect.url").write_text("[InternetShortcut]\nURL=" + url + "\n", encoding="utf-8")
print("Local connection links prepared; no connection token printed.")
