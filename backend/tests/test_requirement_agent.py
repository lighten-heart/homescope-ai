"""需求分析Agent单元测试。

这些测试只验证本地解析逻辑，
不会请求真实大模型。
"""
import pytest
from app.agents.requirement_agent import (
    RequirementAgentError,
    RequirementAnalysisAgent,
)

def test_extract_json_from_markdown_block() -> None:
    """应该能够从Markdown代码块中提取JSON。"""

    raw_output = """
    ```json
    {
    "city": "北京",
    "summary": "希望在北京寻找住房"
    }
    """
    result = RequirementAnalysisAgent._extract_json(
    raw_output
    )
    assert result["city"] == "北京"
    assert result["summary"] == "希望在北京寻找住房"

def test_extract_json_rejects_invalid_output() -> None:
    """没有JSON对象时应该抛出业务异常。"""
    with pytest.raises(RequirementAgentError):
        RequirementAnalysisAgent._extract_json(
                "这里没有任何JSON数据"
        )