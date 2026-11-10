import httpx
import pytest
from hello_agents.core.exceptions import HelloAgentsException
from app.core.config import Settings
from app.services.llm_service import LLMService
from app.services.llm_errors import classify_llm_error


@pytest.mark.parametrize("kind,expected", [
    ("timeout", "llm_timeout"), ("connection", "llm_connection_error"),
    ("server", "llm_server_error"), ("limit", "llm_rate_limited"),
])
def test_wrapped_sdk_error_is_classified_and_not_retried(kind, expected, monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "780")
    settings = Settings(_env_file=None, llm_enabled=True, llm_provider="custom",
        llm_model_id="test", llm_api_key="fake-test-key", llm_base_url="https://example.invalid/v1",
        llm_timeout_seconds=90)
    llm = LLMService(settings).client
    assert llm._client.max_retries == 0
    assert llm._client.timeout.read == 90
    assert llm._client.timeout.connect == 10
    calls = []
    def handle(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("private-upstream-info", request=request)
        if kind == "connection":
            raise httpx.ConnectError("private-upstream-info", request=request)
        return httpx.Response(503 if kind == "server" else 429,
            json={"error":{"message":"private-upstream-info"}}, request=request)
    with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
        original = llm._client
        llm._client = original.with_options(http_client=http_client)
        try:
            with pytest.raises(HelloAgentsException) as exc:
                llm.invoke([{"role":"user","content":"test"}])
            error = classify_llm_error(exc.value, "map_data_agent")
            assert error.code == expected
            assert "private-upstream-info" not in str(error.as_detail())
            assert len(calls) == 1
        finally:
            llm._client.close()
            original.close()
