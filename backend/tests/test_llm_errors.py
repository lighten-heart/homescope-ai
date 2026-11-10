"""复现服务商内容拒绝，不调用真实模型或地图服务。"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from hello_agents.core.exceptions import HelloAgentsException

from app.agents.map_data_agent import MapDataAgent
from app.agents.housing_orchestrator import get_housing_orchestrator
from app.main import app
from app.services.llm_errors import LLMUpstreamError, classify_llm_error


REQUEST_ID = "938639cd-c6f0-4085-8557-42f0666ebf01"
ERROR_TEXT = (
    "LLM调用失败: Error code: 400 - Content Exists Risk "
    f"(request_id: {REQUEST_ID}) key=secret-test-value"
)


def test_content_rejection_has_safe_diagnostic_fields():
    error = classify_llm_error(HelloAgentsException(ERROR_TEXT), "map_data_agent")
    assert error.code == "llm_content_rejected"
    assert error.request_id == REQUEST_ID
    assert "secret-test-value" not in str(error.as_detail())


def test_non_content_error_is_not_misclassified():
    error = classify_llm_error(HelloAgentsException("Error code: 401"), "map_data_agent")
    assert error.code == "llm_upstream_error"
    assert error.request_id is None


def test_wrapped_exception_preserves_request_id():
    original = RuntimeError(ERROR_TEXT)
    wrapper = HelloAgentsException("调用失败")
    wrapper.__cause__ = original
    error = classify_llm_error(wrapper, "map_data_agent")
    assert error.code == "llm_content_rejected"
    assert error.request_id == REQUEST_ID


def test_map_agent_stops_without_retry_or_parsing(housing_request, monkeypatch):
    runner = Mock()
    runner.run.side_effect = HelloAgentsException(ERROR_TEXT)
    monkeypatch.setattr("app.agents.map_data_agent.MapToolAgent", Mock(return_value=runner))
    parser = Mock()
    monkeypatch.setattr("app.agents.map_data_agent.extract_json_object", parser)
    tool = Mock()
    tool.get_expanded_tools.return_value = [Mock()]
    service = SimpleNamespace(tool=tool, check_key_platform=Mock())
    agent = MapDataAgent(SimpleNamespace(client=Mock()), service)
    with pytest.raises(LLMUpstreamError) as exc:
        agent.enrich_with_llm(housing_request, [])
    assert exc.value.code == "llm_content_rejected"
    assert exc.value.stage == "map_data_agent"
    runner.run.assert_called_once()
    parser.assert_not_called()


def test_workflow_returns_actionable_502_not_generic_500(
    client, valid_payload, caplog, monkeypatch,
):
    orchestrator = Mock()
    orchestrator.run.side_effect = classify_llm_error(
        HelloAgentsException(ERROR_TEXT), "map_data_agent"
    )
    monkeypatch.setitem(app.dependency_overrides, get_housing_orchestrator, lambda: orchestrator)
    response = client.post("/api/workflows/housing-decision", json=valid_payload)
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "llm_content_rejected"
    assert detail["request_id"] == REQUEST_ID
    assert detail["stage"] == "map_data_agent"
    assert "secret-test-value" not in response.text
    assert "secret-test-value" not in caplog.text
    assert "Agent结构化输出无效" not in caplog.text
