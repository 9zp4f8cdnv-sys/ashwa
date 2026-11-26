"""The phone app: a small password-protected web server you open in your
phone's browser. Chat with the CEO, approve or deny its requests, see the
team's KPIs and money, and read reports.

The CEO runs in one background worker thread. When it asks for an approval,
the worker waits until you tap Approve or Deny (or the request times out and
counts as denied).
"""

from __future__ import annotations

import hmac
import itertools
import json
import queue
import secrets
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Callable

from flask import Flask, abort, jsonify, request, send_file, session

from .company import CompanyTools
from .db import connect

APPROVAL_TIMEOUT_SECONDS = 30 * 60
PAGE = Path(__file__).with_name("phone.html")


class CEOWorker:
    """Runs CEO turns one at a time and keeps the chat for the web page.

    `start_turn(text, tools, ask)` is the function that really talks to the CEO
    (see `managed_agents_turn`). Tests pass a fake one.
    """

    def __init__(self, db_path, start_turn: Callable, *, staff_runner=None,
                 approval_timeout: float = APPROVAL_TIMEOUT_SECONDS):
        self.db_path = db_path
        self.start_turn = start_turn
        self.staff_runner = staff_runner
        self.approval_timeout = approval_timeout
        self.lock = threading.Lock()
        self.messages: list[dict] = []
        self.pending: dict | None = None
        self.busy = False
        self.inbox: queue.Queue = queue.Queue()
        self._ids = itertools.count(1)
        self._answer: dict | None = None
        self._answered = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    # ------------------------------------------------------------ chat log
    def _add(self, role: str, text: str) -> None:
        with self.lock:
            last = self.messages[-1] if self.messages else None
            if role == "ceo" and last and last["role"] == "ceo" and last.get("open"):
                last["text"] += text  # stream into the current reply
                return
            if last:
                last.pop("open", None)
            self.messages.append({"id": next(self._ids), "role": role, "text": text,
                                  "at": time.strftime("%H:%M"), "open": role == "ceo"})

    def snapshot(self) -> dict:
        with self.lock:
            pending = None
            if self.pending:
                pending = {k: self.pending[k] for k in ("id", "kind", "prompt")}
            return {"messages": [{k: v for k, v in m.items() if k != "open"} for m in self.messages],
                    "busy": self.busy or not self.inbox.empty(), "pending": pending}

    # ---------------------------------------------------------- sending
    def send(self, text: str) -> None:
        self._add("you", text)
        self.inbox.put(text)

    def _loop(self) -> None:
        # The worker thread owns its own DB connection (SQLite connections are per thread).
        tools = CompanyTools(connect(self.db_path), run_staff_task=self.staff_runner,
                             confirm=self._ask_founder)
        while True:
            text = self.inbox.get()
            with self.lock:
                self.busy = True
            try:
                self.start_turn(text, tools, self)
            except Exception as e:  # show the error instead of killing the worker
                self._add("status", f"Error: {e!r}")
            finally:
                with self.lock:
                    self.busy = False
                    if self.messages:
                        self.messages[-1].pop("open", None)

    # ------------------------------------------------------- approvals
    def _wait_for_founder(self, kind: str, prompt: str) -> tuple[bool, str]:
        approval_id = secrets.token_hex(6)
        self._answered.clear()
        with self.lock:
            self._answer = None
            self.pending = {"id": approval_id, "kind": kind, "prompt": prompt}
        self._add("status", "Waiting for your approval")
        got = self._answered.wait(self.approval_timeout)
        with self.lock:
            answer, self._answer, self.pending = self._answer, None, None
        if not got or answer is None:
            self._add("status", "Approval timed out, counted as denied")
            return False, "The founder didn't answer in time. Ask again later."
        self._add("status", ("Approved" if answer["approve"] else "Denied")
                  + (f": {answer['note']}" if answer["note"] else ""))
        return answer["approve"], answer["note"]

    def _ask_founder(self, prompt: str) -> tuple[bool, str]:
        return self._wait_for_founder("approval", prompt)

    def ask_builtin(self, prompt: str) -> bool:
        return self._wait_for_founder("command", prompt)[0]

    def answer(self, approval_id: str, approve: bool, note: str = "") -> bool:
        with self.lock:
            if not self.pending or self.pending["id"] != approval_id:
                return False
            self._answer = {"approve": bool(approve), "note": note.strip()[:1000]}
        self._answered.set()
        return True


def managed_agents_turn(client, state: dict) -> Callable:
    """The real `start_turn`: one Managed Agents session per server run."""
    from .session import SessionRunner, create_session

    holder: dict = {}

    def start_turn(text: str, tools: CompanyTools, worker: CEOWorker) -> None:
        if "runner" not in holder:
            s = create_session(client, state, "CEO (phone)")
            holder["runner"] = SessionRunner(
                client, s.id, tools,
                on_text=lambda t: worker._add("ceo", t),
                on_status=lambda st: worker._add("status", st),
                confirm_builtin=worker.ask_builtin,
            )
        runner = holder["runner"]
        runner.turn(text)
        for path in runner.download_outputs():
            worker._add("status", f"Saved {path}")

    return start_turn


def create_app(worker: CEOWorker, *, password: str, db_path, report_dir: Path = Path("reports"),
               secret_key: str | None = None) -> Flask:
    if not password or len(password) < 8:
        raise ValueError("Set a password of at least 8 characters (ASHWA_PASSWORD).")
    app = Flask(__name__)
    app.secret_key = secret_key or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
    report_dir = Path(report_dir)
    failures: dict[str, list[float]] = {}

    def login_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not session.get("ok"):
                return jsonify(error="login required"), 401
            # JSON-only POSTs with a custom header can't be forged by another site's form.
            if request.method == "POST" and request.headers.get("X-Ashwa") != "1":
                return jsonify(error="bad request"), 400
            return fn(*a, **kw)
        return wrapper

    def company() -> CompanyTools:
        return CompanyTools(connect(db_path), report_dir=report_dir)

    @app.get("/")
    def index():
        return send_file(PAGE, mimetype="text/html")

    @app.post("/api/login")
    def login():
        ip = request.remote_addr or "?"
        recent = [t for t in failures.get(ip, []) if time.time() - t < 600]
        if len(recent) >= 5:
            return jsonify(error="Too many tries. Wait 10 minutes."), 429
        given = (request.get_json(silent=True) or {}).get("password", "")
        if not hmac.compare_digest(str(given).encode(), password.encode()):
            failures[ip] = recent + [time.time()]
            return jsonify(error="Wrong password"), 401
        failures.pop(ip, None)
        session["ok"] = True
        session.permanent = True
        return jsonify(ok=True)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    def me():
        return jsonify(logged_in=bool(session.get("ok")))

    @app.get("/api/chat")
    @login_required
    def chat():
        return jsonify(worker.snapshot())

    @app.post("/api/send")
    @login_required
    def send():
        text = str((request.get_json(silent=True) or {}).get("text", "")).strip()
        if not text:
            return jsonify(error="empty message"), 400
        worker.send(text[:8000])
        return jsonify(ok=True)

    @app.post("/api/review")
    @login_required
    def review():
        from .session import REVIEW_PROMPT
        worker.send(REVIEW_PROMPT)
        return jsonify(ok=True)

    @app.post("/api/answer")
    @login_required
    def answer():
        body = request.get_json(silent=True) or {}
        if not worker.answer(str(body.get("id", "")), bool(body.get("approve")), str(body.get("note", ""))):
            return jsonify(error="That request is no longer waiting."), 409
        return jsonify(ok=True)

    @app.get("/api/company")
    @login_required
    def company_view():
        c = company()
        state = c.get_company_state({})
        state["reviews"] = c.review_staff({})["reviews"]
        state["approvals"] = c._all(
            "SELECT id, kind, summary, amount_cents, status, founder_note, created_at "
            "FROM approvals ORDER BY id DESC LIMIT 50")
        return app.response_class(json.dumps(state, default=str), mimetype="application/json")

    @app.get("/api/reports")
    @login_required
    def reports():
        files = sorted(report_dir.glob("*.md"), reverse=True) if report_dir.exists() else []
        return jsonify([f.name for f in files])

    @app.get("/api/reports/<name>")
    @login_required
    def report(name: str):
        path = (report_dir / name).resolve()
        if path.parent != report_dir.resolve() or path.suffix != ".md" or not path.is_file():
            abort(404)
        return jsonify(name=name, text=path.read_text(encoding="utf-8"))

    return app
