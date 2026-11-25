import json
from types import SimpleNamespace as NS

import pytest

from ashwa.company import ETHICS_AREAS, MAX_ACTIVE_STAFF, CompanyTools, ToolError
from ashwa.db import connect
from ashwa.session import SessionRunner


def run(tools, name, **args):
    return json.loads(tools.run(name, args))


@pytest.fixture
def tools(tmp_path):
    calls = []

    def fake_staff(system, task):
        calls.append((system, task))
        return (f"result of {task}", "FAIL" not in task)

    t = CompanyTools(connect(tmp_path / "c.db"), run_staff_task=fake_staff, report_dir=tmp_path / "reports")
    t.calls = calls
    return t


def hire(tools, role="Marketing", target=10, direction="higher"):
    return run(tools, "hire_agent", role=role, mission="Find customers", system_prompt="You do marketing.",
               kpis=[{"name": "leads", "target": target, "direction": direction}])


def all_checks(rating="pass"):
    return [{"area": a, "rating": rating, "note": "ok"} for a in ETHICS_AREAS]


def test_empty_state_asks_for_interview(tools):
    assert "interview" in run(tools, "get_company_state")["founder_profile"]
    run(tools, "save_founder_profile", fields={"Country": "Australia", "budget": "$2000"})
    run(tools, "save_founder_profile", fields={"budget": "$3000"})
    assert run(tools, "get_company_state")["founder_profile"] == {"country": "Australia", "budget": "$3000"}


def test_task_gets_profile_and_rules(tools):
    run(tools, "save_founder_profile", fields={"country": "Kenya"})
    sid = hire(tools)["staff_id"]
    out = run(tools, "assign_task", staff_id=sid, task="research")
    assert out["status"] == "done"
    system, task = tools.calls[0]
    assert "country: Kenya" in system and "You do marketing." in system and "cannot spend money" in system


def test_stuck_on_kpis_then_rewrite_then_retire(tools):
    h = hire(tools, target=10)
    sid, kpi = h["staff_id"], h["kpis"][0]["id"]
    assert run(tools, "review_staff")["reviews"][0]["status"] == "no_data_yet"
    run(tools, "record_kpi", kpi_id=kpi, value=12, note="ledger")
    run(tools, "record_kpi", kpi_id=kpi, value=3, note="ledger")
    assert run(tools, "review_staff")["reviews"][0]["status"] == "on_track"  # one miss isn't stuck
    run(tools, "record_kpi", kpi_id=kpi, value=4, note="ledger")
    r = run(tools, "review_staff")["reviews"][0]
    assert r["status"] == "stuck" and "two readings" in r["reasons"][0]

    out = run(tools, "rewrite_agent", staff_id=sid, reason="target unrealistic",
              kpis=[{"name": "leads", "target": 3}])
    assert out["version"] == 2
    assert run(tools, "review_staff")["reviews"][0]["status"] == "no_data_yet"  # fresh KPIs

    run(tools, "retire_agent", staff_id=sid, reason="still stuck")
    with pytest.raises(ToolError, match="retired"):
        run(tools, "assign_task", staff_id=sid, task="x")
    new = run(tools, "hire_agent", role="Marketing v2", mission="m", system_prompt="p",
              kpis=[{"name": "leads", "target": 3}], replaces_id=sid)
    assert new["staff_id"] != sid
    changes = tools._all("SELECT change FROM staff_changes ORDER BY id")
    assert [c["change"] for c in changes] == ["hired", "rewritten", "retired", "hired"]


def test_lower_is_better_kpi(tools):
    kpi = hire(tools, target=50, direction="lower")["kpis"][0]["id"]
    for v in (40, 45):
        run(tools, "record_kpi", kpi_id=kpi, value=v, note="x")
    assert run(tools, "review_staff")["reviews"][0]["status"] == "on_track"


def test_stuck_on_failed_tasks(tools):
    sid = hire(tools)["staff_id"]
    run(tools, "assign_task", staff_id=sid, task="FAIL 1")
    run(tools, "assign_task", staff_id=sid, task="FAIL 2")
    assert run(tools, "review_staff")["reviews"][0]["reasons"] == ["last two tasks failed"]


def test_staff_limit(tools):
    for i in range(MAX_ACTIVE_STAFF):
        hire(tools, role=f"r{i}")
    with pytest.raises(ToolError, match="max"):
        hire(tools)


def test_approvals_denied_by_default(tools):
    out = run(tools, "request_approval", kind="spend", summary="Ads", amount=100)
    assert out["status"] == "denied"
    with pytest.raises(ToolError, match="not an approved spend"):
        run(tools, "record_transaction", kind="expense", amount=10, description="ads", approval_id=out["approval_id"])


def test_spend_limit_and_ledger(tools):
    tools.confirm = lambda prompt: (True, "ok")
    a = run(tools, "request_approval", kind="spend", summary="Domain + hosting", amount=50)
    assert a["status"] == "approved"
    run(tools, "record_transaction", kind="expense", amount=30, description="hosting", approval_id=a["approval_id"])
    with pytest.raises(ToolError, match="Only \\$20.00 left"):
        run(tools, "record_transaction", kind="expense", amount=25, description="more", approval_id=a["approval_id"])
    with pytest.raises(ToolError, match="needs approval_id"):
        run(tools, "record_transaction", kind="expense", amount=5, description="sneaky")
    out = run(tools, "record_transaction", kind="income", amount=120, description="first sale")
    assert out["money"] == {"income_cents": 12000, "expense_cents": 3000, "profit_cents": 9000}


def test_launch_needs_passed_ethics_check(tools):
    tools.confirm = lambda prompt: (True, "")
    with pytest.raises(ToolError, match="ethics_check_id"):
        run(tools, "request_approval", kind="launch", summary="Go live")
    with pytest.raises(ToolError, match="Missing"):
        run(tools, "run_ethics_check", item="site", checks=all_checks()[:3])
    bad = all_checks()
    bad[0]["rating"] = "fail"
    failed = run(tools, "run_ethics_check", item="site", checks=bad)
    assert failed["passed"] is False
    with pytest.raises(ToolError, match="has a fail"):
        run(tools, "request_approval", kind="launch", summary="Go live", ethics_check_id=failed["ethics_check_id"])
    ok = run(tools, "run_ethics_check", item="site", checks=all_checks())
    out = run(tools, "request_approval", kind="launch", summary="Go live", ethics_check_id=ok["ethics_check_id"])
    assert out["status"] == "approved"


def test_report_saved(tools):
    out = run(tools, "write_report", title="Week 1 / review", markdown="All good")
    assert open(out["saved"]).read().startswith("# Week 1 / review")


def test_definitions_match_handlers(tools):
    names = {d["name"] for d in tools.definitions()}
    assert names == set(tools._handlers)
    assert "hire_human" not in names and "fire" not in " ".join(names)


class FakeEvents:
    def __init__(self):
        self.sent = []

    def send(self, session_id, events):
        self.sent.extend(events)


def test_runner_sends_tool_result_once(tools):
    client = NS(beta=NS(sessions=NS(events=FakeEvents())))
    r = SessionRunner(client, "sesn_1", tools)
    ev = NS(id="e1", type="agent.custom_tool_use", name="save_customer", input={})
    r.handle(ev)
    r.handle(ev)
    sent = client.beta.sessions.events.sent
    assert len(sent) == 1 and sent[0]["is_error"] is True and "Unknown tool" in sent[0]["content"][0]["text"]
    idle = NS(id="i1", type="session.status_idle", stop_reason=NS(type="end_turn"))
    assert r.handle(idle) is True
