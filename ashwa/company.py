"""The CEO agent's custom tools. They run on *your* machine, against the local
company database, so the company's records never live only in the cloud.

Guardrails are enforced here in code, not just in the prompt:
- Spending, contracts, launches, customer contact, legal filings and any
  decision about real people need the founder's "yes" (request_approval).
- A launch can only be approved with a passed ethics check attached.
- An expense can only be recorded against an approved spend, up to its amount.
- There is no tool to hire or fire a human. The CEO can only recommend it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .db import row_to_dict
from .paths import REPORTS_DIR

MAX_ACTIVE_STAFF = 8

ETHICS_AREAS = [
    "honest_claims",          # no misleading marketing, fake reviews or invented numbers
    "privacy",                # personal data collected, stored and used lawfully
    "consumer_protection",    # fair terms, refunds, clear pricing, no dark patterns
    "legal_registration",     # business, tax and licence requirements met
    "intellectual_property",  # nothing copied; licences in place
    "accessibility",          # usable by people with disabilities where it applies
    "harm",                   # no harm to customers, workers, groups or the public
]

APPROVAL_KINDS = {
    "spend": "Spend money (needs amount)",
    "contract": "Sign or accept any agreement or terms",
    "launch": "Make anything public (needs a passed ethics check)",
    "customer_contact": "Send anything to real customers or prospects",
    "legal_filing": "Register, file or submit anything official",
    "human_staffing": "Recommendation to hire, change or end work with a real person",
    "other": "Anything else the founder should decide",
}

STAFF_RULES = """\
You are a member of an AI staff team working for a small company. Your CEO (another \
AI agent) gives you tasks. The company's owner is a real person, the founder.

Rules that always apply:
- Be truthful. Back factual claims with sources (links) and say how confident you are. \
If you couldn't find something, say so; never invent numbers, quotes or sources.
- You can research and draft. You cannot spend money, sign anything, publish anything \
or contact anyone. Write drafts and recommendations for the CEO instead.
- Stay legal and ethical: no deception, spam, fake reviews, dark patterns, copying \
other people's work, or advice that breaks the law where the founder operates.
- If the task is unclear, impossible or blocked, say exactly what is missing instead \
of guessing. Being honest about being stuck is better than a made-up result.
- End with a short "Result" section: what you did, what you found, and the next step \
you recommend.
"""


class ToolError(Exception):
    """Input the agent should correct (unknown id, missing field, rule broken)."""


StaffTaskFn = Callable[[str, str], tuple[str, bool]]  # (system, task) -> (text, ok)
ConfirmFn = Callable[[str], tuple[bool, str]]          # prompt -> (approved, note)


def _cents(amount: Any) -> int:
    try:
        cents = round(float(amount) * 100)
    except (TypeError, ValueError):
        raise ToolError(f"amount must be a number of dollars, got {amount!r}")
    if cents <= 0:
        raise ToolError("amount must be more than 0")
    return cents


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required,
            "additionalProperties": False}


class CompanyTools:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        run_staff_task: StaffTaskFn | None = None,
        confirm: ConfirmFn = lambda prompt: (False, "No founder is available to approve."),
        report_dir: Path | None = None,
    ):
        self.db = conn
        self.run_staff_task = run_staff_task
        self.confirm = confirm  # default: deny (unattended runs can't approve anything)
        self.report_dir = Path(report_dir) if report_dir is not None else REPORTS_DIR
        self._handlers: dict[str, Callable[[dict], Any]] = {
            name: getattr(self, name) for name in self._schemas()
        }

    # ------------------------------------------------------------- plumbing
    def definitions(self) -> list[dict]:
        return [{"type": "custom", "name": name, "description": desc, "input_schema": schema}
                for name, (desc, schema) in self._schemas().items()]

    def run(self, name: str, args: dict) -> str:
        if name not in self._handlers:
            raise ToolError(f"Unknown tool {name}")
        return json.dumps(self._handlers[name](args), indent=1, default=str)

    def _one(self, sql: str, *params) -> dict | None:
        return row_to_dict(self.db.execute(sql, params).fetchone())

    def _all(self, sql: str, *params) -> list[dict]:
        return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def _staff(self, staff_id: int, active: bool = True) -> dict:
        s = self._one("SELECT * FROM staff WHERE id = ?", staff_id)
        if not s:
            raise ToolError(f"No staff member with id {staff_id}")
        if active and s["status"] != "active":
            raise ToolError(f"Staff {staff_id} ({s['role']}) is retired")
        return s

    @staticmethod
    def _schemas() -> dict[str, tuple[str, dict]]:
        kpi_item = _obj({
            "name": {"type": "string", "description": "What is measured, e.g. 'qualified leads per week'"},
            "target": {"type": "number"},
            "unit": {"type": "string"},
            "direction": {"type": "string", "enum": ["higher", "lower"],
                          "description": "higher = more is better (default); lower = less is better"},
        }, ["name", "target"])
        return {
            "get_company_state": (
                "Everything the company knows right now: founder profile, active staff with "
                "KPIs, money in and out, recent tasks, approvals and decisions. Call this at "
                "the start of every session.",
                _obj({}, []),
            ),
            "save_founder_profile": (
                "Save what you learned about the founder in the interview (country, budget, "
                "hours per week, skills, interests, risk tolerance, income goal, things they "
                "won't do). Pass only the fields you learned; others are kept.",
                _obj({"fields": {"type": "object", "additionalProperties": {"type": "string"},
                                 "description": "e.g. {\"country\": \"Australia\", \"budget\": \"$2,000\"}"}},
                     ["fields"]),
            ),
            "log_decision": (
                "Record a business decision with the reasoning and the sources behind it.",
                _obj({"title": {"type": "string"}, "reasoning": {"type": "string"},
                      "sources": {"type": "array", "items": {"type": "string"}}},
                     ["title", "reasoning"]),
            ),
            "hire_agent": (
                f"Create an AI staff agent (not a person). Give it a role, a mission, a full "
                f"system prompt and 1-3 measurable KPIs. At most {MAX_ACTIVE_STAFF} active at once. "
                "Set replaces_id when it replaces a retired agent.",
                _obj({"role": {"type": "string"}, "mission": {"type": "string"},
                      "system_prompt": {"type": "string"},
                      "kpis": {"type": "array", "items": kpi_item, "minItems": 1, "maxItems": 3},
                      "replaces_id": {"type": "integer"}},
                     ["role", "mission", "system_prompt", "kpis"]),
            ),
            "assign_task": (
                "Give one AI staff agent a task. It researches the web and drafts, then "
                "returns its result. It cannot spend, publish or contact anyone.",
                _obj({"staff_id": {"type": "integer"}, "task": {"type": "string"}},
                     ["staff_id", "task"]),
            ),
            "record_kpi": (
                "Record a KPI reading for an AI staff agent. Only record real measured "
                "values (from the ledger, task results or founder input), never estimates.",
                _obj({"kpi_id": {"type": "integer"}, "value": {"type": "number"},
                      "note": {"type": "string", "description": "Where the number came from"}},
                     ["kpi_id", "value", "note"]),
            ),
            "review_staff": (
                "Performance review of every active AI staff agent: KPIs against target "
                "and recent task results. Flags agents that are stuck.",
                _obj({}, []),
            ),
            "rewrite_agent": (
                "Improve a stuck AI staff agent: new system prompt, mission and/or KPIs. "
                "Give the diagnosed cause as the reason. Its version goes up.",
                _obj({"staff_id": {"type": "integer"}, "reason": {"type": "string"},
                      "system_prompt": {"type": "string"}, "mission": {"type": "string"},
                      "kpis": {"type": "array", "items": kpi_item, "minItems": 1, "maxItems": 3}},
                     ["staff_id", "reason"]),
            ),
            "retire_agent": (
                "Retire an AI staff agent that stays stuck after a rewrite, or whose role "
                "is no longer needed. Its history is kept.",
                _obj({"staff_id": {"type": "integer"}, "reason": {"type": "string"}},
                     ["staff_id", "reason"]),
            ),
            "run_ethics_check": (
                "Record an ethics and legal check of something before it launches. Rate "
                f"every area: {', '.join(ETHICS_AREAS)}. Any 'fail' blocks the launch.",
                _obj({"item": {"type": "string", "description": "What is being checked"},
                      "checks": {"type": "array", "items": _obj({
                          "area": {"type": "string", "enum": ETHICS_AREAS},
                          "rating": {"type": "string", "enum": ["pass", "risk", "fail"]},
                          "note": {"type": "string"}}, ["area", "rating", "note"])}},
                     ["item", "checks"]),
            ),
            "request_approval": (
                "Ask the founder to approve something. Required before any: "
                + "; ".join(f"{k} ({v})" for k, v in APPROVAL_KINDS.items())
                + ". Explain it plainly with costs, risks and the alternative.",
                _obj({"kind": {"type": "string", "enum": list(APPROVAL_KINDS)},
                      "summary": {"type": "string"},
                      "amount": {"type": "number", "description": "Dollars, for spend"},
                      "ethics_check_id": {"type": "integer", "description": "Required for launch"}},
                     ["kind", "summary"]),
            ),
            "record_transaction": (
                "Record money in or out once it has really happened. An expense needs the "
                "id of an approved 'spend' approval and can't exceed what's left on it.",
                _obj({"kind": {"type": "string", "enum": ["income", "expense"]},
                      "amount": {"type": "number", "description": "Dollars"},
                      "description": {"type": "string"},
                      "approval_id": {"type": "integer"}},
                     ["kind", "amount", "description"]),
            ),
            "write_report": (
                "Save the weekly report for the founder as Markdown in reports/. Include: "
                "progress, money in/out, each agent's KPIs, staff changes and why, risks, "
                "and the decisions you need from the founder.",
                _obj({"title": {"type": "string"}, "markdown": {"type": "string"}},
                     ["title", "markdown"]),
            ),
        }

    # ----------------------------------------------------------- the company
    def get_company_state(self, args: dict) -> dict:
        profile = {r["key"]: r["value"] for r in self._all("SELECT key, value FROM founder_profile")}
        staff = self._all("SELECT id, role, mission, version, created_at FROM staff WHERE status = 'active'")
        for s in staff:
            s["kpis"] = self._all(
                "SELECT id, name, target, unit, direction FROM kpis WHERE staff_id = ? AND active = 1", s["id"])
        money = self._one(
            "SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount_cents END), 0) AS income_cents, "
            "COALESCE(SUM(CASE WHEN kind='expense' THEN amount_cents END), 0) AS expense_cents FROM ledger")
        money["profit_cents"] = money["income_cents"] - money["expense_cents"]
        return {
            "founder_profile": profile or "EMPTY - interview the founder first",
            "active_staff": staff,
            "retired_staff_count": self._one("SELECT COUNT(*) AS n FROM staff WHERE status='retired'")["n"],
            "money": money,
            "recent_tasks": self._all(
                "SELECT t.id, t.staff_id, s.role, t.status, substr(t.task, 1, 200) AS task, t.created_at "
                "FROM tasks t JOIN staff s ON s.id = t.staff_id ORDER BY t.id DESC LIMIT 10"),
            "recent_approvals": self._all(
                "SELECT id, kind, summary, amount_cents, status, founder_note, created_at "
                "FROM approvals ORDER BY id DESC LIMIT 10"),
            "recent_decisions": self._all(
                "SELECT id, title, created_at FROM decisions ORDER BY id DESC LIMIT 10"),
            "today": date.today().isoformat(),
        }

    def save_founder_profile(self, args: dict) -> dict:
        fields = args.get("fields") or {}
        if not fields:
            raise ToolError("fields is empty")
        for key, value in fields.items():
            self.db.execute(
                "INSERT INTO founder_profile (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
                (key.strip().lower(), str(value)))
        self.db.commit()
        return {"saved": sorted(fields)}

    def log_decision(self, args: dict) -> dict:
        cur = self.db.execute("INSERT INTO decisions (title, reasoning, sources) VALUES (?, ?, ?)",
                              (args["title"], args["reasoning"], json.dumps(args.get("sources") or [])))
        self.db.commit()
        return {"decision_id": cur.lastrowid}

    # ----------------------------------------------------------- AI staff
    def _add_kpis(self, staff_id: int, kpis: list[dict]) -> None:
        for k in kpis:
            self.db.execute(
                "INSERT INTO kpis (staff_id, name, target, unit, direction) VALUES (?, ?, ?, ?, ?)",
                (staff_id, k["name"], float(k["target"]), k.get("unit", ""), k.get("direction", "higher")))

    def hire_agent(self, args: dict) -> dict:
        active = self._one("SELECT COUNT(*) AS n FROM staff WHERE status = 'active'")["n"]
        if active >= MAX_ACTIVE_STAFF:
            raise ToolError(f"Already {active} active agents (max {MAX_ACTIVE_STAFF}). Retire one first.")
        kpis = args.get("kpis") or []
        if not 1 <= len(kpis) <= 3:
            raise ToolError("Give 1-3 measurable KPIs")
        replaces = args.get("replaces_id")
        if replaces is not None:
            self._staff(replaces, active=False)
        cur = self.db.execute(
            "INSERT INTO staff (role, mission, system_prompt, replaces_id) VALUES (?, ?, ?, ?)",
            (args["role"], args["mission"], args["system_prompt"], replaces))
        staff_id = cur.lastrowid
        self._add_kpis(staff_id, kpis)
        reason = f"Replaces agent {replaces}" if replaces else "New role"
        self.db.execute(
            "INSERT INTO staff_changes (staff_id, change, version, reason, system_prompt) VALUES (?, 'hired', 1, ?, ?)",
            (staff_id, reason, args["system_prompt"]))
        self.db.commit()
        return {"staff_id": staff_id, "kpis": self._all("SELECT id, name, target FROM kpis WHERE staff_id = ?", staff_id)}

    def assign_task(self, args: dict) -> dict:
        s = self._staff(args["staff_id"])
        if self.run_staff_task is None:
            raise ToolError("Staff agents can't run in this session (no API client).")
        profile = "\n".join(f"- {r['key']}: {r['value']}" for r in self._all("SELECT key, value FROM founder_profile"))
        system = (f"{STAFF_RULES}\nYour role: {s['role']}\nYour mission: {s['mission']}\n\n"
                  f"About the founder and company:\n{profile or '(not recorded yet)'}\n\n"
                  f"Your instructions:\n{s['system_prompt']}")
        try:
            text, ok = self.run_staff_task(system, args["task"])
        except Exception as e:  # an API failure is a failed task, not a crashed CEO session
            text, ok = f"Task could not run: {e!r}", False
        cur = self.db.execute(
            "INSERT INTO tasks (staff_id, staff_version, task, result, status) VALUES (?, ?, ?, ?, ?)",
            (s["id"], s["version"], args["task"], text, "done" if ok else "failed"))
        self.db.commit()
        return {"task_id": cur.lastrowid, "staff": s["role"], "status": "done" if ok else "failed", "result": text}

    def record_kpi(self, args: dict) -> dict:
        kpi = self._one("SELECT k.*, s.status FROM kpis k JOIN staff s ON s.id = k.staff_id WHERE k.id = ?",
                        args["kpi_id"])
        if not kpi or not kpi["active"]:
            raise ToolError(f"No active KPI with id {args['kpi_id']}")
        self.db.execute("INSERT INTO kpi_readings (kpi_id, value, note) VALUES (?, ?, ?)",
                        (kpi["id"], float(args["value"]), args["note"]))
        self.db.commit()
        return {"kpi": kpi["name"], "value": args["value"], "target": kpi["target"]}

    @staticmethod
    def _met(value: float, kpi: dict) -> bool:
        return value >= kpi["target"] if kpi["direction"] == "higher" else value <= kpi["target"]

    def review_staff(self, args: dict) -> dict:
        """An agent is 'stuck' when any KPI missed target on its last two readings,
        or its last two tasks failed. The CEO then diagnoses and rewrites or retires it."""
        reviews = []
        for s in self._all("SELECT * FROM staff WHERE status = 'active' ORDER BY id"):
            reasons, kpi_view = [], []
            for k in self._all("SELECT * FROM kpis WHERE staff_id = ? AND active = 1", s["id"]):
                vals = [r["value"] for r in self._all(
                    "SELECT value FROM kpi_readings WHERE kpi_id = ? ORDER BY id DESC LIMIT 2", k["id"])]
                kpi_view.append({"kpi_id": k["id"], "name": k["name"], "target": k["target"],
                                 "direction": k["direction"], "last_readings": vals})
                if len(vals) == 2 and not any(self._met(v, k) for v in vals):
                    reasons.append(f"'{k['name']}' missed target {k['target']:g} two readings in a row "
                                   f"({', '.join(f'{v:g}' for v in vals)})")
            last_tasks = self._all(
                "SELECT id, status, substr(result, 1, 300) AS result_preview FROM tasks "
                "WHERE staff_id = ? AND staff_version = ? ORDER BY id DESC LIMIT 2", s["id"], s["version"])
            if len(last_tasks) == 2 and all(t["status"] == "failed" for t in last_tasks):
                reasons.append("last two tasks failed")
            has_data = any(k["last_readings"] for k in kpi_view) or last_tasks
            reviews.append({
                "staff_id": s["id"], "role": s["role"], "version": s["version"],
                "status": "stuck" if reasons else ("on_track" if has_data else "no_data_yet"),
                "reasons": reasons, "kpis": kpi_view, "recent_tasks": last_tasks,
                "times_rewritten": s["version"] - 1,
            })
        return {
            "reviews": reviews,
            "how_to_act": "For each stuck agent: find the cause (prompt, tools, missing data, impossible "
                          "target, or wrong role). First time stuck: rewrite_agent with the fix. Still stuck "
                          "after a rewrite: retire_agent and hire a replacement with the lessons learned, or "
                          "drop the role. Log every change.",
        }

    def rewrite_agent(self, args: dict) -> dict:
        s = self._staff(args["staff_id"])
        if not any(args.get(k) for k in ("system_prompt", "mission", "kpis")):
            raise ToolError("Change at least one of system_prompt, mission or kpis")
        version = s["version"] + 1
        prompt = args.get("system_prompt") or s["system_prompt"]
        self.db.execute("UPDATE staff SET system_prompt = ?, mission = ?, version = ? WHERE id = ?",
                        (prompt, args.get("mission") or s["mission"], version, s["id"]))
        if args.get("kpis"):
            self.db.execute("UPDATE kpis SET active = 0 WHERE staff_id = ?", (s["id"],))
            self._add_kpis(s["id"], args["kpis"])
        self.db.execute(
            "INSERT INTO staff_changes (staff_id, change, version, reason, system_prompt) VALUES (?, 'rewritten', ?, ?, ?)",
            (s["id"], version, args["reason"], prompt))
        self.db.commit()
        return {"staff_id": s["id"], "version": version,
                "kpis": self._all("SELECT id, name, target FROM kpis WHERE staff_id = ? AND active = 1", s["id"])}

    def retire_agent(self, args: dict) -> dict:
        s = self._staff(args["staff_id"])
        self.db.execute("UPDATE staff SET status = 'retired', retired_reason = ? WHERE id = ?",
                        (args["reason"], s["id"]))
        self.db.execute("UPDATE kpis SET active = 0 WHERE staff_id = ?", (s["id"],))
        self.db.execute(
            "INSERT INTO staff_changes (staff_id, change, version, reason) VALUES (?, 'retired', ?, ?)",
            (s["id"], s["version"], args["reason"]))
        self.db.commit()
        return {"retired": s["id"], "role": s["role"]}

    # -------------------------------------------------- ethics, approvals, money
    def run_ethics_check(self, args: dict) -> dict:
        checks = args.get("checks") or []
        missing = set(ETHICS_AREAS) - {c["area"] for c in checks}
        if missing:
            raise ToolError(f"Rate every area. Missing: {', '.join(sorted(missing))}")
        passed = not any(c["rating"] == "fail" for c in checks)
        cur = self.db.execute("INSERT INTO ethics_checks (item, results, passed) VALUES (?, ?, ?)",
                              (args["item"], json.dumps(checks), int(passed)))
        self.db.commit()
        return {"ethics_check_id": cur.lastrowid, "passed": passed,
                "fails": [c for c in checks if c["rating"] == "fail"],
                "risks": [c for c in checks if c["rating"] == "risk"]}

    def request_approval(self, args: dict) -> dict:
        kind = args["kind"]
        if kind not in APPROVAL_KINDS:
            raise ToolError(f"kind must be one of {', '.join(APPROVAL_KINDS)}")
        amount_cents = _cents(args["amount"]) if args.get("amount") is not None else None
        if kind == "spend" and amount_cents is None:
            raise ToolError("A spend approval needs an amount")
        check_id = args.get("ethics_check_id")
        check = None
        if kind == "launch":
            if check_id is None:
                raise ToolError("A launch needs ethics_check_id from run_ethics_check")
            check = self._one("SELECT * FROM ethics_checks WHERE id = ?", check_id)
            if not check:
                raise ToolError(f"No ethics check {check_id}")
            if not check["passed"]:
                raise ToolError(f"Ethics check {check_id} has a fail. Fix it and check again before launch.")

        lines = [f"APPROVAL NEEDED ({kind}): {args['summary']}"]
        if amount_cents is not None:
            lines.append(f"Amount: ${amount_cents / 100:,.2f}")
        if check:
            risks = [c for c in json.loads(check["results"]) if c["rating"] == "risk"]
            lines.append(f"Ethics check {check_id}: passed" +
                         (f", with risks: {'; '.join(r['area'] + ' - ' + r['note'] for r in risks)}" if risks else ""))
        approved, note = self.confirm("\n".join(lines))

        cur = self.db.execute(
            "INSERT INTO approvals (kind, summary, amount_cents, ethics_check_id, status, founder_note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (kind, args["summary"], amount_cents, check_id, "approved" if approved else "denied", note or ""))
        self.db.commit()
        result = {"approval_id": cur.lastrowid, "status": "approved" if approved else "denied",
                  "founder_note": note or ""}
        if approved and kind == "human_staffing":
            result["reminder"] = "The founder makes and carries out decisions about people. You don't contact them."
        if approved:
            result["reminder_execute"] = ("You have no tool that spends money, signs, publishes or sends anything. "
                                          "Tell the founder exactly what to do, or prepare drafts in outputs/.")
        return result

    def record_transaction(self, args: dict) -> dict:
        cents = _cents(args["amount"])
        approval_id = args.get("approval_id")
        if args["kind"] == "expense":
            if approval_id is None:
                raise ToolError("An expense needs approval_id of an approved spend")
            a = self._one("SELECT * FROM approvals WHERE id = ?", approval_id)
            if not a or a["kind"] != "spend" or a["status"] != "approved":
                raise ToolError(f"Approval {approval_id} is not an approved spend")
            used = self._one("SELECT COALESCE(SUM(amount_cents), 0) AS c FROM ledger "
                             "WHERE approval_id = ? AND kind = 'expense'", approval_id)["c"]
            left = a["amount_cents"] - used
            if cents > left:
                raise ToolError(f"Only ${left / 100:,.2f} left on approval {approval_id}. Ask for a new approval.")
        cur = self.db.execute("INSERT INTO ledger (kind, amount_cents, description, approval_id) VALUES (?, ?, ?, ?)",
                              (args["kind"], cents, args["description"], approval_id))
        self.db.commit()
        return {"ledger_id": cur.lastrowid, "money": self.get_company_state({})["money"]}

    def write_report(self, args: dict) -> dict:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() else "-" for c in args["title"].lower()).strip("-")[:60] or "report"
        path = self.report_dir / f"{date.today().isoformat()}-{slug}.md"
        path.write_text(f"# {args['title']}\n\n{args['markdown']}\n", encoding="utf-8")
        return {"saved": str(path)}
