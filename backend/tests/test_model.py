import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.model import ModelClient, ModelProviderError


@pytest.fixture
def settings():
    return Settings(
        app_mode="live", llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com", llm_api_key="test-only-not-a-secret",
        llm_model="deepseek-flash", _env_file=None,
    )


def install_transport(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr("app.model.httpx.Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    monkeypatch.setattr("app.model.time.sleep", lambda _: None)


def test_deepseek_request_contract(settings, monkeypatch):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content))
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer test-only-not-a-secret"
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}], "usage": {"total_tokens": 17}})

    install_transport(monkeypatch, handler)
    client = ModelClient(settings)
    message, usage = client.complete([{"role": "user", "content": "Return JSON"}])
    assert usage["total_tokens"] == 17
    assert message["content"] == "{}"
    assert captured[0]["thinking"] == {"type": "disabled"}
    assert captured[0]["model"] == "deepseek-flash"
    assert {t["function"]["name"] for t in captured[0]["tools"]} == {"read_error_logs", "read_release_diff", "search_runbooks"}
    client.complete([{"role": "user", "content": "Return JSON"}], allow_tools=False)
    assert "tools" not in captured[1]
    assert captured[1]["response_format"] == {"type": "json_object"}


def test_generic_does_not_receive_deepseek_parameters(settings, monkeypatch):
    settings.llm_provider = "generic"

    def handler(request):
        payload = json.loads(request.content)
        assert "thinking" not in payload
        assert "response_format" not in payload
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "{}"}}]})

    install_transport(monkeypatch, handler)
    ModelClient(settings).complete([], allow_tools=False)


@pytest.mark.parametrize("status,expected,calls", [(401, "密钥无效", 1), (402, "余额不足", 1), (429, "限流", 2), (500, "暂时不可用", 2)])
def test_provider_error_is_safe_and_retries_are_bounded(settings, monkeypatch, status, expected, calls):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "upstream-secret-body"}})

    install_transport(monkeypatch, handler)
    with pytest.raises(ModelProviderError) as caught:
        ModelClient(settings).complete([])
    assert expected in str(caught.value)
    assert "upstream-secret-body" not in str(caught.value)
    assert settings.llm_api_key not in str(caught.value)
    assert len(requests) == calls


def test_transient_error_then_success(settings, monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    install_transport(monkeypatch, handler)
    assert ModelClient(settings).complete([])[0]["content"] == "{}"
    assert calls == 2


def test_output_truncation_does_not_accept_partial_report(settings, monkeypatch):
    install_transport(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}))
    with pytest.raises(ModelProviderError, match="Token 上限"):
        ModelClient(settings).complete([])


def test_key_excluded_from_repr(settings):
    assert settings.llm_api_key not in repr(settings)


def test_safe_provider_error_reaches_task_without_credentials(settings, tmp_path):
    settings.database_url = f"sqlite:///{tmp_path}/app.db"
    settings.checkpoint_url = str(tmp_path / "cp.db")

    class UnfundedModel:
        def complete(self, messages, allow_tools=True):
            raise ModelProviderError("模型账户余额不足，请充值后重试。")

    with TestClient(create_app(settings, model=UnfundedModel())) as client:
        created = client.post("/api/runs", json={"title": "余额错误测试", "description": "测试安全的模型错误传播。", "fixture_id": "null-order"}).json()
        row = client.get(f"/api/runs/{created['id']}").json()
        assert row["status"] == "failed"
        assert "余额不足" in row["error"]
        assert row["ticket"] is None
        assert settings.llm_api_key not in json.dumps(row)
        assert settings.llm_api_key not in client.get("/api/config").text
