"""
Claude Code Proxy
─────────────────
Runs a local HTTP proxy on a configurable port.
- No config toggled  → forwards to https://api.anthropic.com, auth header passed through untouched.
- Config toggled     → forwards to that config's URL, replaces auth header with its token.

Set ANTHROPIC_BASE_URL=http://localhost:<PORT> before starting claude code.
"""

import sys
import json
import os
import threading
import http.server
import http.client
import urllib.parse
import socketserver

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel,
    QScrollArea, QHBoxLayout, QFrame, QLineEdit, QDialog,
    QFileDialog
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIntValidator, QClipboard

CONFIG_FILE   = "configs.json"
DEFAULT_PORT  = 1111
DEFAULT_URL   = "https://api.anthropic.com"

# ── Palette (identical to main.py) ─────────────────────────────────────────
BG       = "#0d1117"
SURFACE  = "#161b22"
BORDER   = "#30363d"
ACCENT   = "#58a6ff"
GREEN    = "#3fb950"
RED      = "#f85149"
MUTED    = "#6e7681"
TEXT     = "#e6edf3"
TEXT_SUB = "#8b949e"
BTN_BG   = "#21262d"
BTN_HVR  = "#30363d"

MAIN_STYLE = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI", -apple-system, sans-serif;
    font-size: 13px;
}}
QLabel {{ color: {TEXT}; background: transparent; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: {SURFACE}; width: 6px; border-radius: 3px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {MUTED}; border-radius: 3px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QPushButton {{
    background: {BTN_BG}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover {{ background: {BTN_HVR}; border-color: {MUTED}; }}
#appTitle {{ font-size: 16px; font-weight: bold; color: {TEXT}; }}
#addBtn {{
    background: {BTN_BG}; color: {ACCENT};
    border: 1px solid {ACCENT}; font-weight: bold; padding: 7px 18px;
}}
#addBtn:hover {{ background: rgba(88,166,255,0.12); }}
#startBtn {{
    background: {GREEN}; color: #0d1117;
    border: none; font-weight: bold; padding: 7px 20px;
}}
#startBtn:hover {{ background: #56d364; }}
#stopBtn {{
    background: {RED}; color: #fff;
    border: none; font-weight: bold; padding: 7px 20px;
}}
#stopBtn:hover {{ background: #ff6b6b; }}
#copyBtn {{
    background: {BTN_BG}; color: {TEXT_SUB};
    border: 1px solid {BORDER}; padding: 0px 10px; font-size: 12px;
}}
#copyBtn:hover {{ background: {BTN_HVR}; color: {TEXT}; border-color: {MUTED}; }}
#portInput {{
    background: {BTN_BG}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 6px;
    padding: 6px 10px; font-size: 12px;
    min-width: 58px; max-width: 58px;
}}
#portInput:focus {{ border-color: {ACCENT}; }}
#statusBar {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 8px 14px;
}}
#statusDot {{ font-size: 11px; font-weight: bold; }}
#statusText {{ font-size: 12px; color: {TEXT_SUB}; }}
#card {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
}}
#card[active="true"] {{ border: 1px solid {GREEN}; }}
#cardTitle {{ font-size: 14px; font-weight: bold; color: {TEXT}; }}
#cardDetails {{ font-size: 12px; color: {TEXT_SUB}; }}
#toggleOff {{
    background: {MUTED}; color: #0d1117; border: none;
    border-radius: 10px; padding: 3px 10px;
    font-size: 11px; font-weight: bold;
    min-width: 44px; max-width: 44px;
}}
#toggleOff:hover {{ background: #8b949e; }}
#toggleOn {{
    background: {GREEN}; color: #0d1117; border: none;
    border-radius: 10px; padding: 3px 10px;
    font-size: 11px; font-weight: bold;
    min-width: 44px; max-width: 44px;
}}
#toggleOn:hover {{ background: #56d364; }}
#editBtn {{
    background: transparent; border: 1px solid {BORDER};
    color: {TEXT_SUB}; padding: 3px 10px; font-size: 12px;
}}
#editBtn:hover {{
    border-color: {ACCENT}; color: {ACCENT};
    background: rgba(88,166,255,0.08);
}}
#deleteBtn {{
    background: transparent; border: 1px solid {BORDER};
    color: {TEXT_SUB}; padding: 3px 10px; font-size: 12px;
}}
#deleteBtn:hover {{
    border-color: {RED}; color: {RED};
    background: rgba(248,81,73,0.08);
}}
"""

DIALOG_STYLE = f"""
QDialog {{ background: {SURFACE}; }}
QLabel {{ color: {TEXT}; background: transparent; }}
#dialogTitle {{ font-size: 15px; font-weight: bold; color: {TEXT}; }}
#fieldLabel {{ font-size: 11px; color: {TEXT_SUB}; font-weight: 600; }}
QLineEdit {{
    background: {SURFACE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 6px;
    padding: 7px 11px; font-size: 13px;
}}
QLineEdit:focus {{ border-color: {ACCENT}; }}
#saveBtn {{
    background: {ACCENT}; color: #0d1117; border: none;
    font-weight: bold; padding: 7px 20px; border-radius: 6px;
}}
#saveBtn:hover {{ background: #79c0ff; }}
#cancelBtn {{
    background: {BTN_BG}; color: {TEXT};
    border: 1px solid {BORDER}; padding: 7px 20px; border-radius: 6px;
}}
#cancelBtn:hover {{ background: {BTN_HVR}; }}
"""


# ── Data ───────────────────────────────────────────────────────────────────

def load_data() -> dict:
    defaults = {"folder": "", "shell": "", "configs": []}
    if not os.path.exists(CONFIG_FILE):
        return defaults
    with open(CONFIG_FILE, "r") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return {**defaults, "configs": raw}
    return {**defaults, **raw}


def save_data(data: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()


# ── Proxy core ─────────────────────────────────────────────────────────────

class ProxyState:
    """Thread-safe description of where to route requests."""

    def __init__(self) -> None:
        self._lock        = threading.Lock()
        self._target_url   = DEFAULT_URL
        self._auth_token   = ""       # empty = pass original auth through
        self._config_name  = ""
        self._model        = ""       # empty = pass original model through
        self._loaded_model = ""       # last model confirmed loaded on the backend

    def set_config(self, url: str, auth_token: str, name: str, model: str = "") -> None:
        with self._lock:
            self._target_url   = url.rstrip("/") or DEFAULT_URL
            self._auth_token   = auth_token
            self._config_name  = name
            self._model        = model
            self._loaded_model = ""   # reset: new backend, unknown state

    def set_default(self) -> None:
        with self._lock:
            self._target_url   = DEFAULT_URL
            self._auth_token   = ""
            self._config_name  = ""
            self._model        = ""
            self._loaded_model = ""

    def snapshot(self) -> tuple[str, str, str, str]:
        with self._lock:
            return self._target_url, self._auth_token, self._config_name, self._model

    def needs_model_switch(self, target: str) -> bool:
        """True only if target differs from what we last confirmed loaded."""
        with self._lock:
            return self._loaded_model != target

    def confirm_loaded(self, model: str) -> None:
        with self._lock:
            self._loaded_model = model



class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """Minimal transparent proxy handler."""

    # Class-level state shared across all handler instances
    proxy_state: ProxyState

    def log_message(self, fmt, *args) -> None:  # suppress noisy access log
        pass

    def _make_conn(self, parsed: urllib.parse.ParseResult) -> http.client.HTTPConnection:
        if parsed.scheme == "https":
            return http.client.HTTPSConnection(parsed.netloc, timeout=60)
        return http.client.HTTPConnection(parsed.netloc, timeout=60)

    def _get_loaded_instance_ids(self, parsed: urllib.parse.ParseResult, auth_token: str) -> list[str]:
        """Return instance IDs of all loaded models via GET /api/v1/models."""
        headers: dict[str, str] = {"Host": parsed.netloc}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        try:
            conn = self._make_conn(parsed)
            conn.request("GET", "/api/v1/models", headers=headers)
            resp = conn.getresponse()
            data = json.loads(resp.read())
            conn.close()
            return [
                instance["id"]
                for model in data.get("models", [])
                for instance in model.get("loaded_instances", [])
            ]
        except Exception:
            return []

    def _unload_model(self, parsed: urllib.parse.ParseResult, instance_id: str, auth_token: str) -> None:
        """POST /api/v1/models/unload to unload a loaded model instance."""
        body = json.dumps({"instance_id": instance_id}).encode()
        headers: dict[str, str] = {
            "Host": parsed.netloc,
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        try:
            conn = self._make_conn(parsed)
            conn.request("POST", "/api/v1/models/unload", body, headers)
            conn.getresponse().read()
            conn.close()
        except Exception:
            pass   # best-effort; do not block the main request

    def _forward(self) -> None:
        target_url, auth_token, _, model = self.proxy_state.snapshot()
        parsed = urllib.parse.urlparse(target_url)
        host = parsed.netloc

        # Read request body
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else None

        # Override model in JSON body if configured, and trigger an unload of
        # the previously loaded model when the active model changes.
        if model and body:
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    payload = json.loads(body)
                    if "model" in payload:
                        payload["model"] = model
                        body = json.dumps(payload).encode()
                        # Only hit the backend when the model has actually changed
                        if self.proxy_state.needs_model_switch(model):
                            for instance_id in self._get_loaded_instance_ids(parsed, auth_token):
                                if instance_id != model:
                                    self._unload_model(parsed, instance_id, auth_token)
                            self.proxy_state.confirm_loaded(model)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        # Build forwarded headers — strip hop-by-hop and auth
        skip = {"host", "x-api-key", "authorization",
                "connection", "transfer-encoding", "keep-alive"}
        fwd: dict[str, str] = {
            k: v for k, v in self.headers.items()
            if k.lower() not in skip
        }
        fwd["Host"] = host
        if body is not None:
            fwd["Content-Length"] = str(len(body))

        if auth_token:
            # Replace auth with the configured token
            fwd["x-api-key"] = auth_token
            fwd.pop("Authorization", None)
        else:
            # Pass original auth through untouched
            if "Authorization" in self.headers:
                fwd["Authorization"] = self.headers["Authorization"]
            if "x-api-key" in self.headers:
                fwd["x-api-key"] = self.headers["x-api-key"]

        try:
            conn = self._make_conn(parsed)

            conn.request(self.command, self.path, body, fwd)
            resp = conn.getresponse()

            self.send_response(resp.status, resp.reason)
            for key, val in resp.getheaders():
                if key.lower() in ("transfer-encoding", "connection"):
                    continue
                self.send_header(key, val)
            self.end_headers()

            # Stream response body in chunks (handles SSE/streaming)
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()

        except Exception as exc:
            try:
                self.send_error(502, f"Proxy error: {exc}")
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    do_GET     = _forward
    do_POST    = _forward
    do_PUT     = _forward
    do_DELETE  = _forward
    do_PATCH   = _forward
    do_HEAD    = _forward
    do_OPTIONS = _forward


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Handle each request in its own thread (required for streaming)."""
    daemon_threads   = True
    allow_reuse_address = True


# ── Config dialog (identical to main.py) ──────────────────────────────────

class ConfigDialog(QDialog):
    def __init__(self, data: dict | None = None):
        super().__init__()
        self.setWindowTitle("Configuration")
        self.setFixedWidth(460)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(24, 22, 24, 22)

        title_lbl = QLabel("Edit Configuration" if data else "New Configuration")
        title_lbl.setObjectName("dialogTitle")
        layout.addWidget(title_lbl)
        layout.addSpacing(10)

        self.name       = QLineEdit(); self.name.setPlaceholderText("e.g. Production, Local…")
        self.url        = QLineEdit(); self.url.setPlaceholderText("https://api.anthropic.com")
        self.auth_token = QLineEdit(); self.auth_token.setPlaceholderText("sk-ant-…")
        self.auth_token.setEchoMode(QLineEdit.Password)
        self.model      = QLineEdit(); self.model.setPlaceholderText("claude-sonnet-4-5")

        for label_text, widget in [
            ("Name", self.name), ("Base URL", self.url),
            ("Auth Token", self.auth_token), ("Model", self.model),
        ]:
            lbl = QLabel(label_text); lbl.setObjectName("fieldLabel")
            layout.addWidget(lbl); layout.addWidget(widget); layout.addSpacing(6)

        layout.addSpacing(10)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        cancel_btn = QPushButton("Cancel"); cancel_btn.setObjectName("cancelBtn")
        save_btn   = QPushButton("Save");   save_btn.setObjectName("saveBtn")
        save_btn.clicked.connect(self.accept); cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(); btn_row.addWidget(cancel_btn); btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        if data:
            self.name.setText(data.get("name", ""))
            self.url.setText(data.get("url", ""))
            self.auth_token.setText(data.get("auth_token", ""))
            self.model.setText(data.get("model", ""))

        self.setStyleSheet(DIALOG_STYLE)

    def get_data(self) -> dict:
        return {
            "name": self.name.text(), "url": self.url.text(),
            "auth_token": self.auth_token.text(), "model": self.model.text(),
        }


# ── Config list item ───────────────────────────────────────────────────────

class ConfigItem(QFrame):
    def __init__(self, config: dict, index: int, parent_app: "App"):
        super().__init__()
        self.config     = config
        self.index      = index
        self.parent_app = parent_app
        self._active    = False

        self.setObjectName("card")
        self.setContentsMargins(14, 10, 14, 10)
        self.setFixedHeight(62)

        row = QHBoxLayout(self); row.setSpacing(10); row.setContentsMargins(0, 0, 0, 0)
        text_col = QVBoxLayout(); text_col.setSpacing(3)

        self.title_lbl = QLabel(config["name"]); self.title_lbl.setObjectName("cardTitle")
        details = QLabel(f"{config['url']}  ·  {config['model']}"); details.setObjectName("cardDetails")
        text_col.addWidget(self.title_lbl); text_col.addWidget(details)

        self.toggle_btn = QPushButton("OFF"); self.toggle_btn.setObjectName("toggleOff")
        self.toggle_btn.setFixedSize(44, 24); self.toggle_btn.clicked.connect(self._on_toggle)

        edit_btn   = QPushButton("Edit");   edit_btn.setObjectName("editBtn");   edit_btn.setFixedHeight(24)
        delete_btn = QPushButton("Delete"); delete_btn.setObjectName("deleteBtn"); delete_btn.setFixedHeight(24)
        edit_btn.clicked.connect(lambda: self.parent_app.edit_config(self.index))
        delete_btn.clicked.connect(lambda: self.parent_app.delete_config(self.index))

        row.addLayout(text_col); row.addStretch()
        row.addWidget(self.toggle_btn); row.addWidget(edit_btn); row.addWidget(delete_btn)

    def set_active(self, active: bool) -> None:
        self._active = active
        self.toggle_btn.setObjectName("toggleOn" if active else "toggleOff")
        self.toggle_btn.setText("ON" if active else "OFF")
        self.setProperty("active", "true" if active else "false")
        for w in (self.toggle_btn, self):
            w.style().unpolish(w); w.style().polish(w)

    def _on_toggle(self) -> None:
        if self._active:
            self.parent_app.clear_active()
        else:
            self.parent_app.set_active(self.index)


# ── Main window ────────────────────────────────────────────────────────────

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Claude Code Proxy")
        self.resize(720, 580)

        data = load_data()
        self.configs: list      = data["configs"]
        self.active_index: int | None = None
        self.items: list[ConfigItem]  = []

        self._proxy_state  = ProxyState()
        self._server: ThreadedHTTPServer | None = None
        self._server_thread: threading.Thread | None = None

        root = QVBoxLayout(self); root.setContentsMargins(20, 18, 20, 18); root.setSpacing(12)

        # Header
        header = QHBoxLayout()
        title = QLabel("Claude Code Proxy"); title.setObjectName("appTitle")
        header.addWidget(title); header.addStretch()
        root.addLayout(header)

        # Scroll list
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.list_layout = QVBoxLayout(self.container)
        self.list_layout.setSpacing(8); self.list_layout.setContentsMargins(0, 0, 4, 0)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll)

        # Status bar
        status_frame = QFrame(); status_frame.setObjectName("statusBar")
        status_row = QHBoxLayout(status_frame); status_row.setContentsMargins(0, 0, 0, 0)
        self._dot_lbl  = QLabel("●"); self._dot_lbl.setObjectName("statusDot")
        self._status_lbl = QLabel("Stopped"); self._status_lbl.setObjectName("statusText")
        self._status_lbl.setMinimumHeight(30)
        status_row.addWidget(self._dot_lbl); status_row.addWidget(self._status_lbl)
        status_row.addStretch()

        self._url_lbl = QLabel(""); self._url_lbl.setObjectName("statusText")
        self._copy_btn = QPushButton("Copy URL"); self._copy_btn.setObjectName("copyBtn")
        self._copy_btn.setFixedHeight(24); self._copy_btn.clicked.connect(self._copy_url)
        self._copy_btn.setHidden(True)
        status_row.addWidget(self._url_lbl); status_row.addWidget(self._copy_btn)
        root.addWidget(status_frame)

        # Bottom bar
        bottom = QHBoxLayout(); bottom.setSpacing(10)
        add_btn = QPushButton("+ Add Configuration"); add_btn.setObjectName("addBtn")
        add_btn.clicked.connect(self.add_config)

        port_label = QLabel("Port:")
        self._port_input = QLineEdit(str(DEFAULT_PORT))
        self._port_input.setObjectName("portInput")
        self._port_input.setValidator(QIntValidator(1024, 65535))

        self._toggle_btn = QPushButton("Start Proxy"); self._toggle_btn.setObjectName("startBtn")
        self._toggle_btn.clicked.connect(self._toggle_proxy)

        bottom.addWidget(add_btn); bottom.addStretch()
        bottom.addWidget(port_label); bottom.addWidget(self._port_input)
        bottom.addWidget(self._toggle_btn)
        root.addLayout(bottom)

        self.setStyleSheet(MAIN_STYLE)
        self._rebuild()
        self._update_status()

    # ── Persistence ────────────────────────────────────────────────────────

    def _persist(self) -> None:
        save_data({"folder": "", "shell": "", "configs": self.configs})

    # ── List management ────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        clear_layout(self.list_layout)
        self.items = []
        for i, config in enumerate(self.configs):
            item = ConfigItem(config, i, self)
            if i == self.active_index:
                item.set_active(True)
            self.items.append(item)
            self.list_layout.addWidget(item)
        self.list_layout.addStretch()

    # ── Toggle ─────────────────────────────────────────────────────────────

    def set_active(self, index: int) -> None:
        if self.active_index is not None and self.active_index < len(self.items):
            self.items[self.active_index].set_active(False)
        self.active_index = index
        if index < len(self.items):
            self.items[index].set_active(True)
        c = self.configs[index]
        self._proxy_state.set_config(c["url"], c["auth_token"], c["name"], c.get("model", ""))
        self._update_status()

    def clear_active(self) -> None:
        if self.active_index is not None and self.active_index < len(self.items):
            self.items[self.active_index].set_active(False)
        self.active_index = None
        self._proxy_state.set_default()
        self._update_status()

    # ── CRUD ───────────────────────────────────────────────────────────────

    def add_config(self) -> None:
        dialog = ConfigDialog()
        if dialog.exec():
            self.configs.append(dialog.get_data()); self._persist()
            self.active_index = None; self._rebuild()

    def edit_config(self, index: int) -> None:
        dialog = ConfigDialog(self.configs[index])
        if dialog.exec():
            self.configs[index] = dialog.get_data(); self._persist(); self._rebuild()
            # Re-apply state if the edited config is currently active
            if index == self.active_index:
                c = self.configs[index]
                self._proxy_state.set_config(c["url"], c["auth_token"], c["name"], c.get("model", ""))
                self._update_status()

    def delete_config(self, index: int) -> None:
        del self.configs[index]; self._persist()
        if self.active_index == index:
            self.active_index = None; self._proxy_state.set_default()
        elif self.active_index is not None and self.active_index > index:
            self.active_index -= 1
        self._rebuild(); self._update_status()

    # ── Proxy control ──────────────────────────────────────────────────────

    def _toggle_proxy(self) -> None:
        if self._server is None:
            self._start_proxy()
        else:
            self._stop_proxy()

    def _start_proxy(self) -> None:
        port_text = self._port_input.text().strip()
        port = int(port_text) if port_text.isdigit() else DEFAULT_PORT

        # Build a handler class with the shared state baked in
        state = self._proxy_state

        class BoundHandler(ProxyHandler):
            proxy_state = state

        try:
            server = ThreadedHTTPServer(("127.0.0.1", port), BoundHandler)
        except OSError as exc:
            self._status_lbl.setText(f"Error: {exc}")
            self._dot_lbl.setStyleSheet(f"color: {RED};")
            return

        self._server = server
        self._server_thread = threading.Thread(
            target=server.serve_forever, daemon=True
        )
        self._server_thread.start()
        self._port_input.setEnabled(False)
        self._toggle_btn.setObjectName("stopBtn")
        self._toggle_btn.setText("Stop Proxy")
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)
        self._update_status()

    def _stop_proxy(self) -> None:
        if self._server:
            # Shutdown blocks until all requests finish; run in a thread
            srv = self._server
            self._server = None
            threading.Thread(target=srv.shutdown, daemon=True).start()

        self._port_input.setEnabled(True)
        self._toggle_btn.setObjectName("startBtn")
        self._toggle_btn.setText("Start Proxy")
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)
        self._update_status()

    # ── Status display ─────────────────────────────────────────────────────

    def _update_status(self) -> None:
        port_text = self._port_input.text().strip()
        port = int(port_text) if port_text.isdigit() else DEFAULT_PORT
        local_url = f"http://localhost:{port}"

        target_url, _, name, model = self._proxy_state.snapshot()

        if self._server is None:
            self._dot_lbl.setText("●")
            self._dot_lbl.setStyleSheet(f"color: {MUTED};")
            self._status_lbl.setText("Stopped")
            self._url_lbl.setText("")
            self._copy_btn.setHidden(True)
        else:
            self._dot_lbl.setText("●")
            self._dot_lbl.setStyleSheet(f"color: {GREEN};")
            route = f"{name}  ({target_url})" if name else target_url
            model_suffix = f"  [{model}]" if model else ""
            self._status_lbl.setText(f"Running  →  {route}{model_suffix}")
            self._url_lbl.setText(f"Proxy URL: {local_url}")
            self._copy_btn.setHidden(False)

    def _copy_url(self) -> None:
        port_text = self._port_input.text().strip()
        port = int(port_text) if port_text.isdigit() else DEFAULT_PORT
        QApplication.clipboard().setText(f"http://localhost:{port}")

    def closeEvent(self, event) -> None:
        self._stop_proxy()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = App()
    w.show()
    sys.exit(app.exec())
