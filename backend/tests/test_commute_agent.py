"""测试真实通勤Agent的解析链，不仅测试协调器中的假Agent。"""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from hello_agents.core.exceptions import HelloAgentsException

from app.agents.commute_agent import CommuteAnalysisAgent
from app.agents.agent_utils import SpecialistAgentError
from app.services.candidate_service import CandidateService
from app.services.llm_errors import LLMUpstreamError


def payload(candidates):
    return {"opinions": [{"candidate_id": c.id, "risk_level": "低",
        "advantages": ["测试优势"], "risks": [], "conclusion": "测试结论"} for c in candidates]}


def make_agent(responses):
    llm = Mock()
    llm.invoke.side_effect = responses
    return CommuteAnalysisAgent(SimpleNamespace(client=llm)), llm


def test_valid_output_requires_only_one_call(housing_request):
    candidates = CandidateService().list_candidates("北京")
    agent, llm = make_agent([json.dumps(payload(candidates))])
    result = agent.analyze(housing_request, candidates)
    assert len(result.opinions) == 3
    assert llm.invoke.call_count == 1
    assert llm.invoke.call_args.kwargs["response_format"] == {"type":"json_object"}
    assert '"enum"' in llm.invoke.call_args.args[0][0]["content"]


@pytest.mark.parametrize("field,value", [
    ("risk_level", "低风险"), ("advantages", "单个字符串"),
    ("risks", None), ("conclusion", None),
])
def test_schema_feedback_can_correct_once(housing_request, field, value):
    candidates = CandidateService().list_candidates("北京")
    good = payload(candidates)
    bad = payload(candidates)
    bad["opinions"][0][field] = value
    agent, llm = make_agent([json.dumps(bad), json.dumps(good)])
    assert len(agent.analyze(housing_request, candidates).opinions) == 3
    assert llm.invoke.call_count == 2
    messages = llm.invoke.call_args.args[0]
    assert f"opinions.0.{field}" in messages[-1]["content"]
    assert candidates[0].id in messages[1]["content"]


@pytest.mark.parametrize("bad,path", [
    ({}, "opinions: missing"),
    ({"opinions": {}}, "opinions: list_type"),
    ({"opinions":[{"candidate_id":"id", "risk_level":"SECRET", "conclusion":"test"}]}, "opinions.0.risk_level: literal_error"),
])
def test_invalid_output_reports_field_without_leaking_value(housing_request, bad, path, caplog):
    candidates = CandidateService().list_candidates("北京")
    agent, llm = make_agent([json.dumps(bad)] * 2)
    with pytest.raises(SpecialistAgentError) as exc:
        agent.analyze(housing_request, candidates)
    assert path in str(exc.value)
    assert "SECRET" not in str(exc.value) + caplog.text
    assert llm.invoke.call_count == 2


def test_provider_rejection_never_triggers_structure_retry(housing_request):
    agent, llm = make_agent([HelloAgentsException("Content Exists Risk")])
    with pytest.raises(LLMUpstreamError) as exc:
        agent.analyze(housing_request, [])
    assert exc.value.stage == "commute_agent"
    assert exc.value.code == "llm_content_rejected"
    assert llm.invoke.call_count == 1


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown"])
def test_candidate_identity_validation_remains_strict(housing_request, kind):
    candidates = CandidateService().list_candidates("北京")
    bad = payload(candidates)
    if kind == "missing":
        bad["opinions"].pop()
    elif kind == "duplicate":
        bad["opinions"].append(dict(bad["opinions"][0]))
    else:
        bad["opinions"][0]["candidate_id"] = "unknown"
    agent, llm = make_agent([json.dumps(bad)])
    with pytest.raises(SpecialistAgentError, match="通勤Agent"):
        agent.analyze(housing_request, candidates)
    assert llm.invoke.call_count == 1
