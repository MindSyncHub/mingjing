"""主 Agent 调度层（薄路由）：MVP 由调用方显式指定 Agent，统一白名单校验。"""
from __future__ import annotations

KNOWN_AGENTS = ("report_gen", "report_qa")


class UnknownAgentError(ValueError):
    def __init__(self, agent: str):
        super().__init__(f"未知 Agent: {agent}（可选 {', '.join(KNOWN_AGENTS)}）")
        self.agent = agent


def resolve_agent(agent: str) -> str:
    agent = (agent or "").strip()
    if agent not in KNOWN_AGENTS:
        raise UnknownAgentError(agent or "<空>")
    return agent
