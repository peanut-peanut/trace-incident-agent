import json

import pytest
from fastapi.testclient import TestClient

from app.agent import demo_report, validate_report
from app.config import Settings
from app.main import create_app
from app.schemas import CreateRun
from app.tools import execute


@pytest.fixture
def settings(tmp_path):
    return Settings(app_mode="demo", database_url=f"sqlite:///{tmp_path}/app.db", checkpoint_url=str(tmp_path / "checkpoints.db"), console_token="", _env_file=None)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def new_run(client, fixture="null-order"):
    response = client.post("/api/runs", json={"title": "测试订单故障", "description": "请结合日志与代码差异排查这个故障。", "fixture_id": fixture})
    assert response.status_code == 202
    return response.json()["id"]


def decision(approved=True):
    return {"approved": approved, "title": "排查订单空状态", "note": "人工确认，先复现。"}


def test_run_stops_before_write(client):
    run_id = new_run(client)
    row = client.get(f"/api/runs/{run_id}").json()
    assert row["status"] == "awaiting_approval", row
    assert row["ticket"] is None
    assert row["report"]["findings"]
    assert row["metrics"]["model_calls"] == 0
    assert row["metrics"]["tool_calls"] == 3


def test_approval_is_idempotent(client):
    run_id = new_run(client)
    assert client.post(f"/api/runs/{run_id}/decision", json=decision()).status_code == 200
    row = client.get(f"/api/runs/{run_id}").json()
    assert row["status"] == "completed", row
    ticket_id = row["ticket"]["id"]
    assert client.post(f"/api/runs/{run_id}/decision", json=decision()).json()["idempotent"]
    assert client.get(f"/api/runs/{run_id}").json()["ticket"]["id"] == ticket_id
    assert client.post(f"/api/runs/{run_id}/decision", json=decision(False)).status_code == 409


def test_reject_does_not_write(client):
    run_id = new_run(client)
    client.post(f"/api/runs/{run_id}/decision", json=decision(False))
    row = client.get(f"/api/runs/{run_id}").json()
    assert row["status"] == "declined"
    assert row["ticket"] is None


def test_durable_approval_after_restart(settings):
    with TestClient(create_app(settings)) as c:
        run_id = new_run(c)
    with TestClient(create_app(settings)) as c:
        assert c.get(f"/api/runs/{run_id}").json()["status"] == "awaiting_approval"
        assert c.post(f"/api/runs/{run_id}/decision", json=decision()).status_code == 200
        assert c.get(f"/api/runs/{run_id}").json()["status"] == "completed"


def test_pending_write_recovers_after_restart(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        run_id = new_run(c)
        app.state.store.transition(run_id, ["awaiting_approval"], "approving", decision=decision())
    with TestClient(create_app(settings)) as c:
        assert c.get(f"/api/runs/{run_id}").json()["status"] == "interrupted"
        assert c.post(f"/api/runs/{run_id}/retry").status_code == 202
        assert c.get(f"/api/runs/{run_id}").json()["status"] == "completed"


@pytest.mark.parametrize("fixture", ["null-order", "stale-chunk", "api-contract"])
def test_synthetic_scenarios(client, fixture):
    row = client.get(f"/api/runs/{new_run(client, fixture)}").json()
    assert row["report"]["confidence"] == "medium"
    assert len(row["report"]["findings"]) == 1
    assert {"LOG-01", "DIFF-01"} <= {e["id"] for e in row["evidence"]}


def test_unknown_input_abstains(client):
    result = client.post("/api/runs", json={"title": "页面偶发不正常", "description": "页面有时候不太正常，目前还没有日志。"}).json()
    row = client.get(f"/api/runs/{result['id']}").json()
    assert row["report"]["confidence"] == "low"
    assert row["report"]["findings"] == []


def test_invalid_fixture(client):
    assert client.post("/api/runs", json={"title": "故障测试", "description": "这是一个不存在的测试案例。", "fixture_id": "nope"}).status_code == 422


def test_ambiguous_fixture_rejected(client):
    assert client.post("/api/runs", json={"title": "故障测试", "description": "不能混合测试与实际的故障证据。", "fixture_id": "null-order", "logs": "custom"}).status_code == 422


def test_missing_run_and_bad_state(client):
    assert client.get("/api/runs/missing").status_code == 404
    run_id = new_run(client)
    assert client.post(f"/api/runs/{run_id}/retry").status_code == 409


def test_tool_allowlist_and_schema():
    with pytest.raises(ValueError):
        execute("run_shell", {"command": "anything"}, {})
    with pytest.raises(ValueError):
        execute("read_error_logs", {"path": "/etc/passwd"}, {"logs": "x"})


def test_redaction():
    data = CreateRun(title="测试安全检查", description="Bearer abcdef-secret secret=hunter2 sk-1234567890abcdef")
    assert "abcdef-secret" not in data.description
    assert "hunter2" not in data.description
    assert "sk-1234567890abcdef" not in data.description


def test_report_rejects_fabricated_citation():
    report = demo_report([{"id": "LOG-01", "content": "Cannot read properties of null"}])
    report["findings"][0]["evidence_ids"] = ["LOG-FAKE"]
    with pytest.raises(ValueError):
        validate_report(report, [{"id": "LOG-01"}])


def test_report_rejects_runbook_only_claim():
    report = demo_report([{"id": "LOG-01", "content": "Cannot read properties of null"}])
    report["findings"][0]["evidence_ids"] = ["KB-NULL"]
    with pytest.raises(ValueError):
        validate_report(report, [{"id": "KB-NULL"}])


def test_auth(settings):
    settings.console_token = "local-test-token"
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/config").status_code == 401
        assert c.get("/api/config", headers={"Authorization": "Bearer local-test-token"}).status_code == 200
        assert "local-test-token" not in c.get("/api/config", headers={"Authorization": "Bearer local-test-token"}).text


def test_sse_and_export(client):
    run_id = new_run(client)
    response = client.get(f"/api/runs/{run_id}/stream")
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: snapshot' in response.text
    assert 'awaiting_approval' in response.text
    assert client.get(f"/api/runs/{run_id}/export").json()["events"]


class StubModel:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, allow_tools=True):
        self.calls += 1
        if self.calls == 1:
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call1", "type": "function", "function": {"name": "read_error_logs", "arguments": "{}"}},
                {"id": "call2", "type": "function", "function": {"name": "run_shell", "arguments": "{}"}},
            ]}, {"total_tokens": 100}
        evidence = json.loads(messages[-2]["content"])
        return {"role": "assistant", "content": json.dumps(demo_report(evidence))}, {"total_tokens": 90}


def test_live_protocol_with_stub_not_real_llm(settings):
    settings.app_mode = "live"
    settings.llm_base_url = "https://example.invalid/v1"
    settings.llm_api_key = "not-a-real-key"
    settings.llm_model = "stub-only"
    with TestClient(create_app(settings, model=StubModel())) as c:
        run_id = new_run(c)
        row = c.get(f"/api/runs/{run_id}").json()
        assert row["status"] == "awaiting_approval", row
        assert row["metrics"]["total_tokens"] == 190
        assert any(e["kind"] == "tool_error" for e in c.get(f"/api/runs/{run_id}/events").json())
        assert row["ticket"] is None


class BadModel:
    def complete(self, messages, allow_tools=True):
        return {"role": "assistant", "content": "not-json"}, {}


def test_invalid_model_output_stops_at_budget(settings):
    settings.app_mode = "live"
    settings.llm_base_url = "https://example.invalid/v1"
    settings.llm_api_key = "not-a-real-key"
    settings.llm_model = "stub-only"
    settings.max_model_rounds = 2
    with TestClient(create_app(settings, model=BadModel())) as c:
        run_id = new_run(c)
        row = c.get(f"/api/runs/{run_id}").json()
        assert row["status"] == "failed"
        assert row["ticket"] is None
        events = c.get(f"/api/runs/{run_id}/events").json()
        assert len([e for e in events if e["kind"] == "model"]) == 2
        assert "not-a-real-key" not in str(row)
