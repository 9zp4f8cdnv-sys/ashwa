import threading
import time

import pytest

from ashwa.web import CEOWorker, create_app

H = {"X-Ashwa": "1"}


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def setup(tmp_path):
    results = {}

    def fake_turn(text, tools, worker):
        if text == "spend":
            out = tools.run("request_approval", {"kind": "spend", "summary": "Buy domain", "amount": 20})
            results["approval"] = out
            worker._add("ceo", "asked")
        else:
            worker._add("ceo", "Hello ")
            worker._add("ceo", "founder")

    db = tmp_path / "c.db"
    worker = CEOWorker(db, fake_turn, approval_timeout=2)
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2026-01-01-week-1.md").write_text("# Week 1\nok")
    (tmp_path / "secret.md").write_text("nope")
    app = create_app(worker, password="correct horse", db_path=db, report_dir=reports, secret_key="k")
    client = app.test_client()
    return client, worker, results


def login(client):
    assert client.post("/api/login", json={"password": "correct horse"}).status_code == 200


def test_password_required(setup):
    client, _, _ = setup
    assert client.get("/").status_code == 200  # the page itself shows a login form
    assert client.get("/api/chat").status_code == 401
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
    for _ in range(4):
        client.post("/api/login", json={"password": "wrong"})
    assert client.post("/api/login", json={"password": "correct horse"}).status_code == 429


def test_short_password_rejected(tmp_path):
    with pytest.raises(ValueError):
        create_app(CEOWorker(tmp_path / "d", lambda *a: None), password="short", db_path=tmp_path / "d")


def test_post_needs_header(setup):
    client, _, _ = setup
    login(client)
    assert client.post("/api/send", json={"text": "hi"}).status_code == 400


def test_chat_streams_into_one_reply(setup):
    client, worker, _ = setup
    login(client)
    assert client.post("/api/send", json={"text": "hi"}, headers=H).status_code == 200
    assert wait_for(lambda: not worker.snapshot()["busy"] and len(worker.snapshot()["messages"]) == 2)
    msgs = client.get("/api/chat").get_json()["messages"]
    assert [(m["role"], m["text"]) for m in msgs] == [("you", "hi"), ("ceo", "Hello founder")]


def test_approval_from_phone(setup):
    client, worker, results = setup
    login(client)
    client.post("/api/send", json={"text": "spend"}, headers=H)
    assert wait_for(lambda: client.get("/api/chat").get_json()["pending"])
    pending = client.get("/api/chat").get_json()["pending"]
    assert "Buy domain" in pending["prompt"] and "$20.00" in pending["prompt"]
    assert client.post("/api/answer", json={"id": "wrong", "approve": True}, headers=H).status_code == 409
    r = client.post("/api/answer", json={"id": pending["id"], "approve": True, "note": "go"}, headers=H)
    assert r.status_code == 200
    assert wait_for(lambda: "approval" in results)
    assert '"approved"' in results["approval"] and '"go"' in results["approval"]
    money = client.get("/api/company").get_json()["approvals"][0]
    assert money["status"] == "approved" and money["amount_cents"] == 2000


def test_approval_times_out_as_denied(setup):
    client, worker, results = setup
    login(client)
    client.post("/api/send", json={"text": "spend"}, headers=H)
    assert wait_for(lambda: "approval" in results, timeout=5)
    assert '"denied"' in results["approval"]
    assert client.get("/api/chat").get_json()["pending"] is None


def test_reports_no_path_escape(setup):
    client, _, _ = setup
    login(client)
    assert client.get("/api/reports").get_json() == ["2026-01-01-week-1.md"]
    assert client.get("/api/reports/2026-01-01-week-1.md").get_json()["text"].startswith("# Week 1")
    assert client.get("/api/reports/..%2Fsecret.md").status_code == 404
    assert client.get("/api/reports/../secret.md").status_code == 404


def test_company_view(setup):
    client, _, _ = setup
    login(client)
    c = client.get("/api/company").get_json()
    assert c["money"]["profit_cents"] == 0 and c["reviews"] == [] and c["approvals"] == []


def test_setup_error_shows_in_chat(tmp_path):
    import anthropic
    import httpx2 as httpx
    from ashwa.web import managed_agents_turn

    def bad_state():
        req = httpx.Request("POST", "https://api.anthropic.com/v1/agents")
        raise anthropic.AuthenticationError("invalid x-api-key", response=httpx.Response(401, request=req), body=None)

    worker = CEOWorker(tmp_path / "d", managed_agents_turn(None, bad_state))
    worker.send("hello")
    assert wait_for(lambda: any("API_KEY was rejected" in m["text"] for m in worker.snapshot()["messages"]))
