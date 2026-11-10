"""将模型上游异常转换为安全的业务错误，不重试或绕过内容风控。"""

import re
import socket
import ssl
import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError


def _connection_diagnostics(chain: list[BaseException]) -> dict[str, object]:
    """只按异常类型分类，不暴露URL、代理凭据或异常原文。"""
    categories = (
        (ssl.SSLError, "tls_error", False),
        (socket.gaierror, "dns_error", False),
        (httpx.ProxyError, "proxy_error", False),
        (httpx.LocalProtocolError, "local_protocol_error", False),
        (httpx.UnsupportedProtocol, "unsupported_protocol", False),
        (httpx.ConnectError, "connect_error", True),
        (httpx.ReadError, "read_error", True),
        (httpx.RemoteProtocolError, "remote_protocol_error", True),
        (httpx.WriteError, "write_error", False),
    )
    for exception_type, reason, retryable in categories:
        if any(isinstance(error, exception_type) for error in chain):
            return {"transport_reason": reason, "retryable": retryable}
    return {"transport_reason": "unknown_connection_error", "retryable": False}


class LLMUpstreamError(RuntimeError):
    """只保存可公开的诊断信息，禁止直接透传供应商原始响应。"""

    def __init__(self, code: str, message: str, stage: str, request_id: str | None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.request_id = request_id
        self.diagnostics: dict[str, object] | None = None

    def as_detail(self) -> dict[str, object]:
        detail = {
            "code": self.code,
            "message": str(self),
            "stage": self.stage,
            "request_id": self.request_id,
        }
        if self.diagnostics is not None:
            detail["diagnostics"] = self.diagnostics
        return detail


def classify_llm_error(exc: Exception, stage: str) -> LLMUpstreamError:
    """识别本次已观察到的风控错误；其他调用失败不误判为风控。

    HelloAgents会将SDK异常包装成HelloAgentsException，因此检查异常链。
    只提取UUID格式的request_id，不记录提示词、地址、密钥或原始错误文本。
    """
    messages: list[str] = []
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        chain.append(current)
        messages.append(str(current))
        current = current.__cause__ or current.__context__

    text = "\n".join(messages)
    match = re.search(
        r"request_id[\s\"':=]+([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})(?![0-9a-z-])",
        text,
        flags=re.IGNORECASE,
    )
    request_id = match.group(1) if match else None
    if "content exists risk" in text.casefold():
        return LLMUpstreamError(
            code="llm_content_rejected",
            message=(
                "模型服务商拒绝了请求内容（Content Exists Risk）。"
                "此次工作流已停止，未自动重试或生成替代地图数据。"
                "请在服务商控制台检查审核记录，或凭request_id联系支持；"
                "此错误不能仅通过更换高德Key或修改JSON格式解决。"
            ),
            stage=stage,
            request_id=request_id,
        )
    # HelloAgents包装后仍保留异常链；按实际类型分类，而不是猜测字符串。
    if any(isinstance(e, (APITimeoutError, httpx.TimeoutException, TimeoutError)) for e in chain):
        return LLMUpstreamError(
            "llm_timeout", "模型服务请求超时；SDK自动重试已关闭，请检查网络和请求规模。",
            stage, request_id,
        )
    if any(isinstance(e, APIConnectionError) for e in chain):
        error = LLMUpstreamError(
            "llm_connection_error", "无法连接模型服务或连接中断，请检查网络和服务可用性。",
            stage, request_id,
        )
        error.diagnostics = _connection_diagnostics(chain)
        return error
    status_error = next((e for e in chain if isinstance(e, APIStatusError)), None)
    if status_error is not None and status_error.status_code >= 500:
        return LLMUpstreamError(
            "llm_server_error", "模型服务端返回5xx错误；本地未自动重试。",
            stage, request_id,
        )
    if status_error is not None and status_error.status_code == 429:
        return LLMUpstreamError(
            "llm_rate_limited", "模型服务返回429，请检查调用额度或限流设置。",
            stage, request_id,
        )
    return LLMUpstreamError(
        code="llm_upstream_error",
        message="模型服务调用失败，请检查模型服务状态、访问权限和配置。",
        stage=stage,
        request_id=request_id,
    )
