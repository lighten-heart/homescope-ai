"""专家连接中断的有限恢复；全部使用替身，不调用模型服务。"""

import socket
import ssl
from threading import Event
from unittest.mock import Mock

import httpx
import pytest
from hello_agents.core.exceptions import HelloAgentsException
from openai import APIConnectionError

from app.core.parallel_execution import ParallelAgentRunner
from app.services.llm_errors import LLMUpstreamError, classify_llm_error


def wrapped_connection(cause=None):
    sdk_error = APIConnectionError(
        request=httpx.Request("POST", "https://example.invalid/v1/chat/completions"),
    )
    sdk_error.__cause__ = cause
    error = HelloAgentsException("private-transport-detail")
    error.__cause__ = sdk_error
    return error


@pytest.mark.parametrize("cause,reason,retryable", [
    (httpx.ConnectError("secret"), "connect_error", True),
    (httpx.ReadError("secret"), "read_error", True),
    (httpx.RemoteProtocolError("secret"), "remote_protocol_error", True),
    (httpx.ProxyError("secret"), "proxy_error", False),
    (httpx.WriteError("secret"), "write_error", False),
    (socket.gaierror("secret"), "dns_error", False),
    (ssl.SSLCertVerificationError("secret"), "tls_error", False),
    (None, "unknown_connection_error", False),
])
def test_safe_transport_classification(cause, reason, retryable):
    error = classify_llm_error(wrapped_connection(cause), "facility_agent")
    assert error.code == "llm_connection_error"
    assert error.diagnostics == {"transport_reason": reason, "retryable": retryable}
    assert "secret" not in str(error.as_detail())
    assert "private-transport-detail" not in str(error.as_detail())


def test_tls_cause_overrides_outer_connect_error():
    transport = httpx.ConnectError("secret")
    transport.__cause__ = ssl.SSLCertVerificationError("private-certificate")
    error = classify_llm_error(wrapped_connection(transport), "facility_agent")
    assert error.diagnostics == {"transport_reason": "tls_error", "retryable": False}


def test_only_failed_expert_retries_after_sibling_finished(monkeypatch, caplog):
    monkeypatch.setattr("app.core.parallel_execution.time.sleep", lambda _: None)
    facility_failed = Event()
    commute_finished = Event()

    def commute_operation():
        assert facility_failed.wait(5)
        commute_finished.set()
        return "commute-result"

    count = 0

    def facility_operation():
        nonlocal count
        count += 1
        if count == 1:
            facility_failed.set()
            raise wrapped_connection(httpx.ReadError("secret"))
        assert commute_finished.is_set()
        return "facility-result"

    commute = Mock(side_effect=commute_operation)
    facility = Mock(side_effect=facility_operation)
    first, second, durations = ParallelAgentRunner().run_pair(
        first_stage="commute_agent", first_operation=commute,
        second_stage="facility_agent", second_operation=facility,
    )
    assert (first, second) == ("commute-result", "facility-result")
    commute.assert_called_once()
    assert facility.call_count == 2
    assert all(value >= 0 for value in durations.values())
    assert "specialist_connection_retry" in caplog.text
    assert "secret" not in caplog.text


def test_second_connection_failure_is_propagated_without_loop(monkeypatch):
    monkeypatch.setattr("app.core.parallel_execution.time.sleep", lambda _: None)
    facility = Mock(side_effect=wrapped_connection(httpx.ReadError("secret")))
    commute = Mock(return_value="ok")
    with pytest.raises(LLMUpstreamError) as exc:
        ParallelAgentRunner().run_pair(
            first_stage="commute_agent", first_operation=commute,
            second_stage="facility_agent", second_operation=facility,
        )
    assert exc.value.code == "llm_connection_error"
    assert facility.call_count == 2
    commute.assert_called_once()


@pytest.mark.parametrize("error", [
    wrapped_connection(httpx.ProxyError("secret")),
    wrapped_connection(httpx.WriteError("secret")),
    wrapped_connection(socket.gaierror("secret")),
    wrapped_connection(ssl.SSLCertVerificationError("secret")),
    wrapped_connection(httpx.ReadTimeout("secret")),
    wrapped_connection(),
    HelloAgentsException("Content Exists Risk"),
    LLMUpstreamError("llm_rate_limited", "limited", "facility_agent", None),
])
def test_nonrecoverable_errors_are_not_retried(error):
    facility = Mock(side_effect=error)
    with pytest.raises(LLMUpstreamError):
        ParallelAgentRunner().run_pair(
            first_stage="commute_agent", first_operation=lambda: "ok",
            second_stage="facility_agent", second_operation=facility,
        )
    facility.assert_called_once()


def test_recovery_can_be_disabled():
    facility = Mock(side_effect=wrapped_connection(httpx.ConnectError("secret")))
    with pytest.raises(LLMUpstreamError):
        ParallelAgentRunner(connection_retry_enabled=False).run_pair(
            first_stage="commute_agent", first_operation=lambda: "ok",
            second_stage="facility_agent", second_operation=facility,
        )
    facility.assert_called_once()


def test_tool_agent_is_never_retried_by_specialist_policy():
    map_operation = Mock(side_effect=wrapped_connection(httpx.ConnectError("secret")))
    with pytest.raises(LLMUpstreamError):
        ParallelAgentRunner().run_pair(
            first_stage="map_data_agent", first_operation=map_operation,
            second_stage="facility_agent", second_operation=lambda: "ok",
        )
    map_operation.assert_called_once()
