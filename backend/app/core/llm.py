"""LLM 调用与知识库加载的公共底座（2026-10-15 减法：自 stage35.py 抽出）。

stage35 流水线已废弃（gen-audit 替代，bddfdca），本模块保留仍被
report_qa（追问）与评测脚本复用的通用件：API 配置、直连调用、JSON 解析、知识装载。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
# ranran monorepo 布局：疗愈知识库在仓库根 knowledge/healing/。
# 知识条目相对 KB_ROOT；产品自有文档相对 REPO_ROOT，以 docs/ 前缀区分。
KB_ROOT = REPO_ROOT.parent.parent / "knowledge" / "healing"  # products/mingjing → ranran 仓库根

_ONTOLOGY_FILES = ["本体/语义层/状态.md", "本体/语义层/概念与关系.md"]
KNOWLEDGE_FILES = [
    *_ONTOLOGY_FILES,
    "本体/语义层/议题.md",
    "术/流派/曼陀罗/视觉信号映射.md",
    "术/流派/曼陀罗/五行解读.md",
    "术/流派/曼陀罗/直断解读.md",
    "术/流派/曼陀罗/组合模式.md",
    "术/流派/曼陀罗/状态五行映射.md",
    "术/流派/曼陀罗/议题解读.md",
    "本体/出方案/状态疗愈映射.md",
    "本体/语义层/状态解释.md",
    "docs/报告模板.md",
]
CANDIDATE_KNOWLEDGE_FILES = [
    *_ONTOLOGY_FILES,
    "本体/语义层/议题.md",
    "术/流派/曼陀罗/视觉信号映射.md",
    "术/流派/曼陀罗/五行解读.md",
    "术/流派/曼陀罗/直断解读.md",
    "术/流派/曼陀罗/组合模式.md",
    "术/流派/曼陀罗/状态五行映射.md",
    "术/流派/曼陀罗/议题解读.md",
    "本体/出方案/状态疗愈映射.md",
]


class LLMError(RuntimeError):
    pass


def _parse_json_response(text: str, label: str) -> dict[str, Any]:
    """解析模型 JSON；允许 markdown fenced JSON，但不允许静默修补。"""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMError(f"{label} 返回不是合法 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMError(f"{label} 返回必须是 JSON object")
    return value


def _load_knowledge(files: list[str] | None = None) -> tuple[str, list[str]]:
    chunks: list[str] = []
    used: list[str] = []
    for relative in (files if files is not None else KNOWLEDGE_FILES):
        path = (REPO_ROOT / relative) if relative.startswith("docs/") else (KB_ROOT / relative)
        if not path.exists():
            raise LLMError(f"知识文件不存在: {path}")
        used.append(relative)
        chunks.append(f"\n===== SOURCE: {relative} =====\n{path.read_text(encoding='utf-8')}\n")
    return "".join(chunks), used


def _api_config() -> dict[str, str]:
    settings = Settings()
    kimi_key = settings.kimi_api_key.strip()
    deepseek_key = settings.deepseek_api_key.strip()
    missing = [name for name, value in (("KIMI_API_KEY", kimi_key), ("DEEPSEEK_API_KEY", deepseek_key)) if not value]
    if missing:
        raise LLMError("缺少模型 API key: " + ", ".join(missing))
    return {
        "kimi_key": kimi_key,
        "deepseek_key": deepseek_key,
        "kimi_url": settings.kimi_base_url.rstrip("/") + "/chat/completions",
        "deepseek_url": settings.deepseek_base_url.rstrip("/") + "/chat/completions",
        "kimi_model": settings.kimi_model,
        "deepseek_model": settings.deepseek_model,
    }


def _usage(response: dict[str, Any]) -> dict[str, Any]:
    usage = response.get("usage") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }


def _direct_chat(*, url: str, key: str, model: str, messages: list[dict[str, Any]],
                 label: str, json_mode: bool = True, temperature: float = 0.2,
                 reasoning_effort: str | None = None) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    started = time.perf_counter()
    payload = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                url,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=300) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            if exc.code < 500:
                raise LLMError(f"{label} API 调用失败: HTTP {exc.code}: {detail}") from exc
            last_error = LLMError(f"HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(2 ** attempt)
    if payload is None:
        raise LLMError(f"{label} API 调用失败（3 次尝试）: {last_error}") from last_error
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"{label} API 返回缺少 choices[0].message.content") from exc
    if not isinstance(content, str):
        raise LLMError(f"{label} 返回 content 不是文本")
    return content, {"model": model, "elapsed_ms": int((time.perf_counter() - started) * 1000), "usage": _usage(payload)}
