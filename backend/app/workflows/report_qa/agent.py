"""WF-REPORT-QA：报告锚定 + 规则护栏 + 工具化检索（一期 3 工具）+ LLM 生成。

六工具序列已全部落地（spec 2.2/3.4）：report_search / state_query /
knowledge_retrieve / reason_chain / five_elements_reason / intervention_query。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.guard import audit_output, check_input
from app.workflows.report_qa import tools as qa_tools
from app.core.llm import (
    REPO_ROOT,
    _api_config,
    _direct_chat,
    _load_knowledge,
    _parse_json_response,
)

DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"

_KNOWLEDGE_CACHE: tuple[str, list[str]] | None = None


def _knowledge_with_cache() -> tuple[str, list[str]]:
    """知识库进程内缓存：避免每轮问答重复读盘拼接（评测/多轮场景省延迟）。"""
    global _KNOWLEDGE_CACHE
    if _KNOWLEDGE_CACHE is None:
        _KNOWLEDGE_CACHE = _load_knowledge()
    return _KNOWLEDGE_CACHE


def _load_context(run_dir: Path) -> dict[str, Any]:
    """三级链路产物加载：优先 context.json；缺失时（新 run 结构）从 hypotheses.json 合成。

    合成口径：state_hypotheses → linkage.states，knowledge_refs → knowledge_rule_refs，
    供 state_query 按 state_id/状态名/规则引用匹配（spec 3.4）。
    """
    context_path = run_dir / "context.json"
    if context_path.exists():
        return json.loads(context_path.read_text(encoding="utf-8"))
    hyp_path = run_dir / "hypotheses.json"
    if hyp_path.exists():
        try:
            hyp = json.loads(hyp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"linkage": {"states": []}}
        states = [{
            "state_id": s.get("state_id"), "name": s.get("name", ""),
            "level": s.get("level"), "confidence": s.get("confidence"),
            "knowledge_rule_refs": s.get("knowledge_refs") or [],
        } for s in (hyp.get("state_hypotheses") or [])]
        return {"linkage": {"states": states}}
    return {"linkage": {"states": []}}
SCENARIOS = ("advisor", "reply_prep")
SCENARIO_ROUND_LIMITS = {"advisor": 30, "reply_prep": 15}  # spec 2.3 轮次硬限
FOLLOWUP_ACTIONS = ("regenerate", "reclassify")  # spec 2.5 回答后操作


def _find_last_turn(run_dir: Path, question: str) -> dict[str, Any] | None:
    """回答后操作定位：同一问题最近一次落盘 turn（沿用其分类与检索参数）。"""
    qa_dir = Path(run_dir) / "qa"
    if not qa_dir.exists():
        return None
    for path in sorted(qa_dir.glob("turn-*.json"), reverse=True):
        try:
            turn = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if turn.get("question") == question:
            return turn
    return None
HISTORY_MAX_MESSAGES = 10  # 窗口内原文保留条数（5 轮问答），超出部分滚动摘要
QUESTION_TYPES = ("细节追问", "深度探讨", "视角切换", "方案细化", "跨议题关联", "应答组织")
_DEGRADE_ANSWER = "该问题暂无法安全回答，建议参考报告相关章节。"


def _persist_turn(run_dir: Path, *, scenario: str, question: str, answer: str,
                  question_type: str | None = None, sources: list[dict[str, Any]] | None = None,
                  confidence: float | None = None, safety_level: str | None = None,
                  audit: str = "pass", extra: dict[str, Any] | None = None,
                  blocked_category: str | None = None) -> Path | None:
    """轮次留痕（spec 2.3/D-094）：一问一文件 turn-NNNN.json；护栏拒绝与降级话术同等待遇落盘。

    只写 qa/ 子目录，报告产物只读不写。返回落盘路径；run_dir 不可写时返回 None（不阻断回答）。
    """
    try:
        qa_dir = Path(run_dir) / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        turn_no = len(list(qa_dir.glob("turn-*.json"))) + 1
        payload: dict[str, Any] = {
            "turn": turn_no,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scenario": scenario,
            "question": question,
            "question_type": question_type,
            "answer": answer,
            "sources": sources or [],
            "audit": audit,  # pass / degraded（降级话术）/ blocked（护栏拒绝）
        }
        if confidence is not None:
            payload["confidence"] = confidence
        if safety_level is not None:
            payload["safety_level"] = safety_level
        if blocked_category is not None:
            payload["blocked_category"] = blocked_category
        if extra:
            payload.update(extra)
        path = qa_dir / f"turn-{turn_no:04d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except OSError:
        return None


def _persist_block_if_run_exists(runs_root: Path, report_id: str, *, scenario: str,
                                 question: str, answer: str, blocked_category: str) -> None:
    """Step A 拦截/个案风险提示：报告目录存在时把拒绝落盘为正式回答（历史可见，避免重复踩红线）。"""
    run_dir = Path(runs_root) / report_id
    if (run_dir / "report.md").exists():
        _persist_turn(run_dir, scenario=scenario, question=question, answer=answer,
                      audit="blocked", blocked_category=blocked_category)


def _render_turn(turn: dict[str, Any]) -> str:
    role = (turn.get("role") or "").strip().lower()
    prefix = "答" if role == "assistant" else "问"
    return f"{prefix}：{turn.get('content', '')}"


def _summarize_history(older: list[dict[str, Any]], config: dict[str, str]) -> str:
    """超窗部分滚动摘要（spec 2.3）：保留主题、结论与关键术语，200 字内。"""
    transcript = "\n".join(_render_turn(m) for m in older)
    prompt = (
        "把以下问答对话压缩为 200 字内的摘要，保留：讨论过的主题、已达成的结论、关键术语。\n"
        f"对话：\n{transcript}\n\n只输出摘要文本。"
    )
    content, _ = _direct_chat(
        url=config["deepseek_url"], key=config["deepseek_key"], model=config["deepseek_model"],
        messages=[{"role": "user", "content": prompt}], label="QA 历史摘要", json_mode=False, temperature=0.0,
    )
    return (content or "").strip()


def _build_history_block(conversation_history: list[dict[str, Any]] | None,
                         config: dict[str, str]) -> str:
    """对话历史 → prompt 文本块；报告内容始终常驻（由调用方单独注入），历史超窗滚动摘要。"""
    if not conversation_history:
        return ""
    turns = [m for m in conversation_history if isinstance(m, dict) and m.get("content")]
    if not turns:
        return ""
    if len(turns) <= HISTORY_MAX_MESSAGES:
        return "【对话历史】\n" + "\n".join(_render_turn(m) for m in turns)
    summary = _summarize_history(turns[:-HISTORY_MAX_MESSAGES], config)
    recent = "\n".join(_render_turn(m) for m in turns[-HISTORY_MAX_MESSAGES:])
    return f"【早前对话摘要】{summary}\n【近期对话】\n{recent}"


def _classify(question: str, config: dict[str, str]) -> tuple[str, float, str, str, str, list[str]]:
    """Step B：问题分类 + 检索参数提取（一次调用）。

    返回 (question_type, confidence, search_query, state_key, target_id, elements)——
    后四者是工具调用的参数决策（spec 3.2：LLM 决定参数，程序执行工具）：
    target_id = state_id/claim_id/失衡名（reason_chain/intervention_query 用）；
    elements = 两个元素如 ["火","金"]（five_elements_reason 用，不足两个则为空）。
    """
    prompt = (
        "你是疗愈师报告问答助手的任务分类器。把疗愈师的问题归入六类之一，无法归入按「细节追问」处理。\n"
        "六类：细节追问 / 深度探讨 / 视角切换 / 方案细化 / 跨议题关联 / 应答组织。\n"
        "同时提取检索参数：search_query = 检索关键词短语（核心实体：状态名、术语、颜色）；"
        "state_key = 明确提到的状态名或 state_id（如 S-002，没有则为空字符串）；"
        "target_id = 问题聚焦的 state_id / claim_id / 失衡模式名（如 火乘金，没有则为空字符串）；"
        "elements = 问题中涉及的两个五行元素（颜色/形状/元素名，如 [\"红\",\"白\"]，不足两个则为空数组）。\n"
        f"问题：{question}\n"
        '只输出 JSON：{"question_type":"六类之一","confidence":0.0~1.0,'
        '"search_query":"关键词","state_key":"状态名或空","target_id":"S-NNN/C-NN/失衡名或空",'
        '"elements":["元素1","元素2"]}'
    )
    content, _ = _direct_chat(
        url=config["deepseek_url"], key=config["deepseek_key"], model=config["deepseek_model"],
        messages=[{"role": "user", "content": prompt}], label="QA 问题分类", json_mode=True, temperature=0.0,
    )
    data = _parse_json_response(content, "QA 问题分类")
    qt = data.get("question_type") or "细节追问"
    if qt not in QUESTION_TYPES:
        qt = "细节追问"
    try:
        confidence = float(data.get("confidence") or 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    search_query = str(data.get("search_query") or "").strip()
    state_key = str(data.get("state_key") or "").strip()
    target_id = str(data.get("target_id") or "").strip()
    raw_elements = data.get("elements") or []
    elements = [str(e).strip() for e in raw_elements if str(e).strip()][:2] if isinstance(raw_elements, list) else []
    return qt, confidence, search_query, state_key, target_id, elements


def _generate(question: str, question_type: str, scenario: str, report_md: str,
              context: dict[str, Any], accepted_claims: list[dict[str, Any]],
              knowledge: str, config: dict[str, str], correction: str = "",
              history_block: str = "") -> tuple[str, list[dict[str, Any]], bool]:
    linkage = context.get("linkage", {})
    prompt = (
        "你是疗愈师端的报告问答助手，读者是疗愈师（不直接面对来访者）。\n"
        f"问题类型：{question_type}；场景：{scenario}（advisor=解读参谋，reply_prep=应答准备）。\n"
        "回答要求：必须锚定报告正文或三级链路产物，禁止编造报告外内容；超范围内容标「这是延伸探讨，不是报告结论」；"
        "不用诊断/承诺/绝对化/评判性语言，不替来访者做重大决定。\n"
        '只输出 JSON：{"answer":"回答文本","sources":[{"knowledge_rule_ref":"规则ID","claim_id":"claim_id","quote":"报告原文片段"}],"is_beyond_report":false}\n\n'
        "【报告正文】\n" + report_md + "\n\n"
        "【三级链路确定性产物】\n" + json.dumps(linkage, ensure_ascii=False) + "\n\n"
        "【相关依据 claims】\n" + json.dumps(accepted_claims[:40], ensure_ascii=False) + "\n\n"
        "【检索结果】\n" + knowledge + "\n\n"
        + (history_block + "\n\n" if history_block else "")
        + f"疗愈师问题：{question}\n"
        + (f"补充纠正要求：{correction}\n" if correction else "")
    )
    content, _ = _direct_chat(
        url=config["deepseek_url"], key=config["deepseek_key"], model=config["deepseek_model"],
        messages=[{"role": "user", "content": prompt}], label="QA 生成", json_mode=True, temperature=0.3,
    )
    data = _parse_json_response(content, "QA 生成")
    answer = data.get("answer") or ""
    sources = data.get("sources") or []
    if not isinstance(sources, list):
        sources = []
    return answer, sources, bool(data.get("is_beyond_report"))


def _generate_with_safety(question: str, question_type: str, scenario: str, report_md: str,
                          context: dict[str, Any], accepted_claims: list[dict[str, Any]],
                          knowledge: str, config: dict[str, str],
                          history_block: str = "", supplement: str = "") -> tuple[str, list[dict[str, Any]], bool]:
    """supplement = 疗愈师"再生成一版"时附的补充要求（spec 2.5），首轮生成即注入。

    工程容错（spec 2.4：LLM 调用失败 Retry）：JSON 解析失败/空回答计一次重试，
    最多 3 次后降级——单轮坏输出不拖垮整轮问答。
    """
    safety_level = "L2" if scenario == "reply_prep" else "L1"
    correction = supplement
    answer, sources, is_beyond = "", [], False
    for _ in range(3):
        try:
            answer, sources, is_beyond = _generate(
                question, question_type, scenario, report_md, context, accepted_claims,
                knowledge, config, correction, history_block,
            )
        except Exception:
            answer, sources, is_beyond = "", [], False
        if not answer.strip():
            correction = (correction + " " if correction else "") + "上次输出为空或格式非法，请严格只输出合法 JSON。"
            continue
        audit = audit_output(answer, safety_level)
        if not audit.blocked:
            break
        if audit.rewritten:
            if not audit_output(audit.rewritten, safety_level).blocked:
                answer = audit.rewritten
                break
        correction = "请用可能性/非诊断/接纳性表述，不替来访者做重大决定，不用「一定/肯定/绝对/所有/永远/必须」等词。"
    else:
        answer = _DEGRADE_ANSWER
        sources, is_beyond = [], False
    if not sources:
        refs: list[str] = []
        for claim in accepted_claims:
            for ref in claim.get("knowledge_rule_refs") or []:
                if ref and ref not in refs:
                    refs.append(ref)
        sources = [{"knowledge_rule_ref": ref} for ref in refs]
    return answer, sources, is_beyond


def list_turns(*, report_id: str, runs_root: Path = DEFAULT_RUNS_ROOT) -> list[dict[str, Any]]:
    """问答历史回读（spec 2.6）：只读 qa/ 子目录，按轮次升序返回落盘 turn 全文。

    report_id 无效或目录无 qa/ 子目录时返回空数组，不报错。
    """
    qa_dir = Path(runs_root) / report_id / "qa"
    if not qa_dir.is_dir():
        return []
    turns = []
    for path in sorted(qa_dir.glob("turn-*.json")):
        try:
            turns.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return turns


def answer_question(*, report_id: str, user_question: str, scenario: str = "advisor",
                    conversation_history: list[dict[str, str]] | None = None,
                    runs_root: Path = DEFAULT_RUNS_ROOT,
                    action: str | None = None, override_type: str | None = None,
                    supplement: str = "") -> dict[str, Any]:
    """报告问答入口：Step A 输入安全 → 加载报告上下文 → Step B 分类 → Step C/D 生成+审核 → Step E 组装。

    conversation_history 参与生成（spec 2.3）：窗口内原文保留，超窗滚动摘要；
    轮次达场景硬限后正常应答并提示开启新会话。
    """
    conversation_history = conversation_history or []
    scenario = scenario or "advisor"
    if scenario not in SCENARIOS:
        raise ValueError(f"未知场景: {scenario}")
    if action is not None and action not in FOLLOWUP_ACTIONS:
        raise ValueError(f"未知操作: {action}（可选 {', '.join(FOLLOWUP_ACTIONS)}）")

    guard = check_input(user_question)
    if guard.blocked or guard.case_risk:
        category = "crisis_case_risk" if guard.case_risk else guard.category
        _persist_block_if_run_exists(runs_root, report_id, scenario=scenario,
                                     question=user_question, answer=guard.message,
                                     blocked_category=category or "unknown")
        return {
            "blocked": True,
            "category": category,
            "message": guard.message,
            "report_id": report_id,
            "scenario": scenario,
        }

    run_dir = Path(runs_root) / report_id
    report_path = run_dir / "report.md"
    if not report_path.exists():
        raise ValueError(f"report_id 无效或产物缺失: {report_id}")

    report_md = report_path.read_text(encoding="utf-8")
    context = _load_context(run_dir)
    claims_path = run_dir / "claims.json"
    claims = json.loads(claims_path.read_text(encoding="utf-8")).get("claims", []) if claims_path.exists() else []
    accepted_claims = [c for c in claims if c.get("status") == "accepted"]
    knowledge, _ = _knowledge_with_cache()
    config = _api_config()

    action_meta: dict[str, Any] = {}
    if action == "regenerate":
        # 再生成一版：沿用上一turn分类与检索参数，不重跑 Step B（spec 2.5）；
        # 无历史时回退正常分类。补充要求首轮注入生成。
        prev = _find_last_turn(run_dir, user_question)
        if prev and prev.get("question_type"):
            question_type = prev["question_type"]
            confidence = prev.get("confidence", 0.5)
            prev_args = prev.get("search_args") or {}
            search_query = prev_args.get("search_query") or user_question
            state_key = prev_args.get("state_key") or ""
            target_id = prev_args.get("target_id") or ""
            elements = prev_args.get("elements") or []
        else:
            question_type, confidence, search_query, state_key, target_id, elements = _classify(user_question, config)
        action_meta = {"action": "regenerate"}
        if supplement:
            action_meta["supplement"] = supplement
    elif action == "reclassify":
        # 指错重分类：人工指定类型覆盖 Step B，重走 C→D→E 并留痕（spec 2.5）
        if not override_type:
            raise ValueError("指错重分类必须提供 override_type（六类之一）")
        if override_type not in QUESTION_TYPES:
            raise ValueError(f"override_type 必须是六类之一: {override_type}")
        question_type = override_type
        confidence = 1.0  # 人工修正视为确定
        _, _, search_query, state_key, target_id, elements = _classify(user_question, config)  # 只取检索参数
        action_meta = {"action": "reclassify", "override_type": override_type, "human_corrected": True}
    else:
        question_type, confidence, search_query, state_key, target_id, elements = _classify(user_question, config)

    # 轮次硬限：正常路径按传入历史计；回答后操作按已落盘轮次计（spec 2.5：操作计入上限）
    if action is None:
        rounds = len([m for m in conversation_history if isinstance(m, dict)]) // 2
    else:
        rounds = len(list((run_dir / "qa").glob("turn-*.json"))) if (run_dir / "qa").exists() else 0
    round_limit_hit = rounds >= SCENARIO_ROUND_LIMITS[scenario]

    history_block = _build_history_block(conversation_history, config)
    tool_results = qa_tools.run_tools(
        question_type, search_query=search_query, state_key=state_key,
        report_md=report_md, context=context, knowledge=knowledge,
        trace_dir=run_dir, target_id=target_id, elements=elements,
    )
    retrieval_block = qa_tools.render_tool_results(tool_results)
    answer, sources, is_beyond = _generate_with_safety(
        user_question, question_type, scenario, report_md, context, accepted_claims,
        retrieval_block or "（本轮检索无命中，只能依据报告正文与链路产物回答）", config,
        history_block, supplement,
    )
    if round_limit_hit:
        answer += "\n\n（已达本场景轮次上限，建议开启新会话）"
        result_limit: dict[str, Any] = {"round_limit": True}
    else:
        result_limit = {}

    result: dict[str, Any] = {
        "report_id": report_id,
        "scenario": scenario,
        "question_type": question_type,
        "confidence": confidence,
        "safety_level": "L2" if scenario == "reply_prep" else "L1",
        "answer": answer,
        "sources": sources,
    }
    if is_beyond:
        result["boundary_note"] = "这是延伸探讨，不是报告结论"
    if scenario == "reply_prep":
        result["caveat"] = "能量层面的参考，不是诊断；必要时寻求专业帮助"
    result.update(result_limit)

    extra = {k: result[k] for k in ("boundary_note", "caveat", "round_limit") if k in result}
    extra["search_args"] = {"search_query": search_query, "state_key": state_key,
                            "target_id": target_id, "elements": elements}
    extra.update(action_meta)
    _persist_turn(run_dir, scenario=scenario, question=user_question, answer=answer,
                  question_type=question_type, sources=sources, confidence=confidence,
                  safety_level=result["safety_level"],
                  audit="degraded" if answer == _DEGRADE_ANSWER else "pass", extra=extra)
    return result
