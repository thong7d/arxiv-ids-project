"""Official Colab MCP entrypoint with an explicit Windows browser handoff.

The connection URL contains a short-lived token, so it is saved only in ignored
local artifacts. It is never written to stdout, Git or the notebook.
"""

import json
import logging
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import colab_mcp
from colab_mcp.session import ColabProxyClient
from colab_mcp.websocket_server import ColabWebSocketServer

_start_proxy_client = ColabProxyClient._start_proxy_client
_websocket_init = ColabWebSocketServer.__init__


def ipv4_websocket_init(self, host="127.0.0.1"):
    # Windows localhost + port=0 can allocate DIFFERENT IPv4/IPv6 ports.
    # One address family ensures the port put in Google's UI is unambiguous.
    _websocket_init(self, host=host)


async def traced_start_proxy(self):
    try:
        # Do not spend the MCP initialization timeout while the user is still
        # signing in or granting browser local-network permission.
        await self.wss.connection_live.wait()
        await _start_proxy_client(self)
    except Exception:
        logging.exception("Colab MCP initialization failed")
        raise


def capture_connection(url):
    parts = urlsplit(url)
    # Reopen the verified saved course notebook, retaining Google's local
    # proxy fragment, so a runtime restart does not create another scratch copy.
    url = urlunsplit(parts._replace(path="/drive/1Lpghcw747yNcuHbJDZKMnHtdSZKofAto"))
    directory = Path(__file__).resolve().parents[1] / "artifacts" / "colab"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "connection.json").write_text(json.dumps({"url": url}), encoding="utf-8")
    return False


if __name__ == "__main__":
    webbrowser.open_new = capture_connection
    ColabProxyClient._start_proxy_client = traced_start_proxy
    ColabWebSocketServer.__init__ = ipv4_websocket_init
    logging.getLogger("websockets.server").setLevel(logging.INFO)
    colab_mcp.main()
