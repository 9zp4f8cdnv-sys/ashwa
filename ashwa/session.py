"""Drives one Managed Agents session for the CEO: sends messages, runs the
company tools locally, passes approval requests to the founder, and reports
the CEO's text through callbacks.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import anthropic

from .company import CompanyTools, ToolError
from .paths import OUTPUTS_DIR, STATE_FILE  # noqa: F401  (STATE_FILE re-exported)


GREETING = "Hello. Check where we are and tell me what you need from me."
REVIEW_PROMPT = (
    "Weekly review. Check company state, record any real KPI numbers you have, run "
    "review_staff, fix or replace stuck agents as your instructions say, then write_report. "
    "Finish by listing the decisions you need from me."
)


class SessionRunner:
    def __init__(
        self,
        client: anthropic.Anthropic,
        session_id: str,
        tools: CompanyTools,
        *,
        on_text: Callable[[str], None] = lambda t: None,
        on_status: Callable[[str], None] = lambda s: None,
        confirm_builtin: Callable[[str], bool] = lambda prompt: False,
    ):
        self.client = client
        self.session_id = session_id
        self.tools = tools
        self.on_text = on_text
        self.on_status = on_status
        self.confirm_builtin = confirm_builtin  # unattended runs leave the default: deny
        self.seen: set[str] = set()

    def send(self, events: list[dict]) -> None:
        self.client.beta.sessions.events.send(session_id=self.session_id, events=events)

    def send_text(self, text: str) -> None:
        self.send([{"type": "user.message", "content": [{"type": "text", "text": text}]}])

    def turn(self, text: str) -> bool:
        """Send a message and process events until the CEO finishes its turn.
        Returns False if the stream couldn't be (re)established."""
        sent = False
        for attempt in range(5):
            try:
                with self.client.beta.sessions.events.stream(session_id=self.session_id) as stream:
                    if not sent:  # stream-first: open the stream, then send
                        self.send_text(text)
                        sent = True
                    else:  # reconnect: replay anything missed while disconnected
                        for ev in self.client.beta.sessions.events.list(session_id=self.session_id, order="asc"):
                            if self.handle(ev):
                                return True
                    for ev in stream:
                        if self.handle(ev):
                            return True
                return True
            except (anthropic.APIConnectionError, anthropic.APITimeoutError) as e:
                self.on_status(f"stream dropped: {e}; reconnecting")
                time.sleep(min(2 ** attempt, 10))
        self.on_status("could not reconnect")
        return False

    def handle(self, ev) -> bool:
        """Process one event. Returns True when the turn is over."""
        if ev.id in self.seen:
            return False
        self.seen.add(ev.id)

        if ev.type == "agent.message":
            for block in ev.content:
                if block.type == "text":
                    self.on_text(block.text)
        elif ev.type in ("agent.tool_use", "agent.mcp_tool_use"):
            if getattr(ev, "evaluated_permission", None) == "ask":
                self.review_builtin(ev)
            else:
                self.on_status(ev.name)
        elif ev.type == "agent.custom_tool_use":
            self.run_custom_tool(ev)
        elif ev.type == "session.error":
            self.on_status(f"session error: {getattr(ev, 'error', ev)}")
        elif ev.type == "session.status_idle":
            # requires_action = waiting on us (tool result or approval): keep streaming.
            return ev.stop_reason.type != "requires_action"
        elif ev.type == "session.status_terminated":
            self.on_status("session ended")
            return True
        return False

    def execute_tool(self, name: str, args: dict) -> tuple[str, bool]:
        try:
            return self.tools.run(name, args), False
        except ToolError as e:
            return str(e), True
        except Exception as e:  # keep the session alive on unexpected bugs
            return f"Internal error in {name}: {e!r}", True

    def run_custom_tool(self, ev) -> None:
        name, args = ev.name, dict(ev.input or {})
        preview = json.dumps(args)
        self.on_status(f"{name} {preview[:160]}{'…' if len(preview) > 160 else ''}")
        result, is_error = self.execute_tool(name, args)
        self.send([{
            "type": "user.custom_tool_result",
            "custom_tool_use_id": ev.id,
            "content": [{"type": "text", "text": result}],
            "is_error": is_error,
        }])

    def review_builtin(self, ev) -> None:
        """A container tool call the server flagged for review (permission policy `auto`)."""
        preview = json.dumps(getattr(ev, "input", {}) or {})[:400]
        allowed = self.confirm_builtin(f"CEO wants to run {ev.name}: {preview}\nAllow?")
        self.send([{"type": "user.tool_confirmation", "tool_use_id": ev.id,
                    "result": "allow" if allowed else "deny"}])

    def download_outputs(self, out_root: Path = OUTPUTS_DIR, retries: int = 1) -> list[Path]:
        out_dir = out_root / self.session_id
        files = []
        for attempt in range(retries):  # files are indexed a second or two after idle
            files = list(self.client.beta.files.list(scope_id=self.session_id, betas=["managed-agents-2026-04-01"]))
            if files or attempt == retries - 1:
                break
            time.sleep(1.5)
        saved = []
        for f in files:
            target = out_dir / f.filename
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            self.client.beta.files.download(f.id).write_to_file(target)
            saved.append(target)
        return saved


def create_session(client: anthropic.Anthropic, state: dict, title: str):
    return client.beta.sessions.create(
        agent={"type": "agent", "id": state["agent_id"], "version": state["agent_version"]},
        environment_id=state["environment_id"],
        title=title,
    )
