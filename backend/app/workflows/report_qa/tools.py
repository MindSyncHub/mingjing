"""WF-REPORT-QA 检索工具（L1 结构化路由 + L2 关键词召回，spec 3.4 接口契约）。

纯函数实现：输入确定输出确定；LLM 只决定调用参数（检索词/state_key），不接触文件系统。
向量召回为规模开关后的 L3 升级位，本期不实现（见 knowledge-base.md 结构化 RAG 设计）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_HEADING = re.compile(r"^#{1,4}\s+(.+)$", re.M)
_RULE_ID = re.compile(r"\b(?:CP|IM|S|C|T|D)-\d{2,3}\b")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_NON_WORD = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff]+")

DEFAULT_TOP_K = 5


def _terms(query: str) -> set[str]:
    """查询 → 匹配词元：CJK 连续段取 2-gram 滑窗，拉丁/数字取整词。"""
    terms: set[str] = set()
    for run in _CJK_RUN.findall(query or ""):
        if len(run) == 1:
            terms.add(run)
        terms.update(run[i:i + 2] for i in range(len(run) - 1))
    terms.update(w.lower() for w in _NON_WORD.split(query or "") if len(w) >= 2 and not _CJK_RUN.fullmatch(w))
    return terms


def _score(text: str, terms: set[str]) -> int:
    if not terms:
        return 0
    low = text.lower()
    return sum(1 for t in terms if t in low)


def _chunk_markdown(text: str) -> list[dict[str, Any]]:
    """Markdown → 带章节锚点的块：按标题分段，段内再按空行分段。"""
    chunks: list[dict[str, Any]] = []
    anchor = ""
    for section in re.split(r"(?=^#{1,4}\s+)", text, flags=re.M):
        section = section.strip()
        if not section:
            continue
        m = _HEADING.match(section)
        if m:
            anchor = m.group(1).strip()
            body = section[m.end():].strip()
        else:
            body = section
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if para:
                chunks.append({"anchor": anchor, "text": para})
    return chunks


def _top_hits(chunks: list[dict[str, Any]], query: str, top_k: int) -> list[dict[str, Any]]:
    terms = _terms(query)
    if not terms:
        return []
    # 评分计入章节锚点：标题是信息密度最高的匹配对象，但返回的正文不含标题
    scored = [(_score((c["anchor"] + "\n" + c["text"]) if c["anchor"] else c["text"], terms), i, c)
              for i, c in enumerate(chunks)]
    hits = [s for s in scored if s[0] > 0]
    hits.sort(key=lambda s: (-s[0], s[1]))
    return [{"anchor": c["anchor"], "text": c["text"], "score": s} for s, _, c in hits[:top_k]]


def report_search(report_md: str, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """报告内检索（spec 3.4）：返回命中的段落原文 + 章节锚点。"""
    if not query or not report_md:
        return []
    return _top_hits(_chunk_markdown(report_md), query, top_k)


def state_query(states: list[dict[str, Any]], key: str, top_k: int = 3) -> list[dict[str, Any]]:
    """本体论状态查询（spec 3.4）：state_id 精确匹配优先，状态名子串匹配兜底。"""
    key = (key or "").strip()
    if not key or not states:
        return []
    exact = [s for s in states if s.get("state_id") == key]
    if exact:
        return exact[:top_k]
    return [s for s in states if key in str(s.get("state_id", "")) or key in str(s.get("name", ""))
            or any(key in str(r) for r in (s.get("knowledge_rule_refs") or []))][:top_k]


def knowledge_retrieve(knowledge: str, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """知识库检索（spec 3.4）：关键词召回命中单元原文 + 规则 ID；L3 向量召回为规模开关后升级位。"""
    if not query or not knowledge:
        return []
    hits = _top_hits(_chunk_markdown(knowledge), query, top_k)
    for h in hits:
        h["rule_ids"] = sorted(set(_RULE_ID.findall(h["text"])))
    return hits


# ---------- reason_chain：解读 trace 推导链（spec 3.4） ----------

_TRACE_VLINE = re.compile(r"^- \[(V-\d+)\] (.+)$", re.M)


def _load_trace(trace_dir: Path) -> dict[str, Any]:
    """读取 runs/<report_id>/ 解读 trace（只读，QA 不写链路产物，spec 3.5）。"""
    trace: dict[str, Any] = {"observations": {}, "v_lines": {}, "hypotheses": {}, "claims": []}
    trace_dir = Path(trace_dir)
    obs_path = trace_dir / "observations.json"
    if obs_path.exists():
        try:
            obs = json.loads(obs_path.read_text(encoding="utf-8"))
            for o in (obs.get("observations") or []):
                if o.get("observation_id"):
                    trace["observations"][o["observation_id"]] = o
        except (OSError, json.JSONDecodeError):
            pass
    analysis_path = trace_dir / "analysis.md"
    if analysis_path.exists():
        for vid, text in _TRACE_VLINE.findall(analysis_path.read_text(encoding="utf-8")):
            trace["v_lines"][vid] = text.strip()
    hyp_path = trace_dir / "hypotheses.json"
    if hyp_path.exists():
        try:
            trace["hypotheses"] = json.loads(hyp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    claims_path = trace_dir / "claims.json"
    if claims_path.exists():
        try:
            trace["claims"] = json.loads(claims_path.read_text(encoding="utf-8")).get("claims") or []
        except (OSError, json.JSONDecodeError):
            pass
    return trace


def reason_chain(trace_dir: Path, target_id: str) -> list[dict[str, Any]]:
    """推导链：信号 → 失衡 → 状态 → 议题 各级证据（spec 3.4）。

    target_id 可为 state_id（S-NNN）、claim_id（C-NNN）或失衡名（IM-NN）。
    """
    target_id = (target_id or "").strip()
    if not target_id:
        return []
    trace = _load_trace(trace_dir)
    hyp = trace["hypotheses"]

    states = [s for s in (hyp.get("state_hypotheses") or [])
              if s.get("state_id") == target_id
              or target_id in (s.get("knowledge_refs") or [])]
    claims = [c for c in trace["claims"]
              if c.get("claim_id") == target_id
              or any(target_id in str(r) for r in (c.get("knowledge_rule_refs") or []))]
    imbalances = [i for i in (hyp.get("imbalance_hypotheses") or []) if i.get("name") == target_id]
    if not (states or claims or imbalances):
        return []

    # 目标锚定的观察 ID 集合：状态/claims 的支撑观察 + 失衡的支撑观察
    anchor_ids: set[str] = set()
    for s in states:
        anchor_ids.update(s.get("support_observation_ids") or [])
    for c in claims:
        anchor_ids.update(c.get("source_observation_ids") or [])
    for i in imbalances:
        anchor_ids.update(i.get("support_observation_ids") or [])

    # 议题：支撑观察与锚集有交集
    topics = [tp for tp in (hyp.get("topic_hypotheses") or [])
              if anchor_ids & set(tp.get("support_observation_ids") or [])]
    # 失衡兜底：状态引用但锚集未覆盖时，按 imbalance_ref 关联
    if not imbalances:
        refs = {s.get("imbalance_ref") for s in states if s.get("imbalance_ref")}
        imbalances = [i for i in (hyp.get("imbalance_hypotheses") or []) if i.get("name") in refs]

    def signal_item(sid: str) -> dict[str, Any]:
        obs = trace["observations"].get(sid) or {}
        return {"id": sid, "ring": obs.get("ring", ""),
                "text": trace["v_lines"].get(sid, obs.get("kind", ""))}

    chain: list[dict[str, Any]] = []
    signals = [signal_item(sid) for sid in sorted(anchor_ids) if sid.startswith(("V-", "K-"))]
    if signals:
        chain.append({"layer": "信号", "items": signals})
    if imbalances:
        chain.append({"layer": "失衡", "items": [
            {"name": i.get("name"), "cause": i.get("cause_element"),
             "result": i.get("result_element"),
             "support": i.get("support_observation_ids") or []} for i in imbalances]})
    if states:
        chain.append({"layer": "状态", "items": [
            {"state_id": s.get("state_id"), "level": s.get("level"),
             "knowledge_refs": s.get("knowledge_refs") or []} for s in states]})
    if claims and not states:
        chain.append({"layer": "结论", "items": [
            {"claim_id": c.get("claim_id"), "text": c.get("text"),
             "confidence": c.get("confidence")} for c in claims[:5]]})
    if topics:
        chain.append({"layer": "议题", "items": [
            {"topic": tp.get("topic"), "confidence": tp.get("confidence")} for tp in topics]})
    return chain


# ---------- five_elements_reason：五行生克（spec 3.4） ----------

_ELEMENTS = ("金", "木", "水", "火", "土")
_SHENG = {"金": "水", "水": "木", "木": "火", "火": "土", "土": "金"}   # 相生：我生
_KE = {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"}     # 相克：我克
# 元素名归一化最小映射。口径源：五行解读.md 生克规则 + 视觉信号映射.md 形状五行（D-091）；
# 代码表仅覆盖常见颜色/形状，口径变更以知识库为准。
_ELEMENT_ALIASES = {
    "红": "火", "赤": "火", "橙": "火", "紫": "火",
    "黄": "土", "褐": "土", "棕": "土",
    "绿": "木", "青": "木",
    "蓝": "水", "黑": "水", "灰": "水",
    "白": "金", "金": "金", "银": "金",
    "尖": "火", "三角": "火", "星": "火",
    "圆": "金", "弧": "金",
    "长": "木", "条": "木", "柱": "木",
    "波": "水", "曲": "水", "旋": "水", "涡": "水",
    "方": "土", "块": "土", "正": "土",
}


def _to_element(value: str) -> str | None:
    value = (value or "").strip()
    if value in _ELEMENTS:
        return value
    for alias, element in _ELEMENT_ALIASES.items():
        if alias in value:
            return element
    return None


def five_elements_reason(elements: list[str]) -> dict[str, Any] | None:
    """两个元素（颜色/形状/宫位/元素名）→ 生克关系判定 + 结构化依据（spec 3.4）。"""
    if not elements or len(elements) < 2:
        return None
    a, b = _to_element(elements[0]), _to_element(elements[1])
    if not a or not b:
        return None
    if a == b:
        relation, basis = "比和", f"{a}与{b}同元素，不比生克，论强弱"
    elif _SHENG.get(a) == b:
        relation, basis = f"{a}生{b}", f"相生环：{a}生{b}（{_SHENG[a]}为{a}所生）"
    elif _SHENG.get(b) == a:
        relation, basis = f"{b}生{a}", f"相生环：{b}生{a}（{a}为{b}所生）"
    elif _KE.get(a) == b:
        relation, basis = f"{a}克{b}", f"相克环：{a}克{b}"
    else:
        relation, basis = f"{b}克{a}", f"相克环：{b}克{a}"
    return {"elements": [a, b], "relation": relation, "basis": basis,
            "source": "五行解读.md 生克规则 + 视觉信号映射.md 形状五行（D-091 口径）"}


# ---------- intervention_query：疗愈方案检索（spec 3.4，知识库 L4 方案层） ----------

_INTERVENTION_MARKERS = ("T-", "方案", "冥想", "练习", "调理", "动作", "步骤", "干预")


def intervention_query(knowledge: str, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    """方案层检索：关键词召回后按干预标记过滤，非方案内容不进结果。"""
    hits = knowledge_retrieve(knowledge, query, top_k * 2)
    filtered = [h for h in hits
                if any(r.startswith("T-") for r in (h.get("rule_ids") or []))
                or any(m in (h.get("anchor", "") + h["text"]) for m in _INTERVENTION_MARKERS)]
    return filtered[:top_k]


# 各问题类型的工具序列（spec 2.2 全表；六工具序列本期全部落地）
TOOL_SEQUENCES: dict[str, tuple[str, ...]] = {
    "细节追问": ("report_search", "state_query", "knowledge_retrieve"),
    "深度探讨": ("state_query", "reason_chain", "knowledge_retrieve"),
    "视角切换": ("state_query", "knowledge_retrieve"),
    "方案细化": ("intervention_query", "knowledge_retrieve"),
    "跨议题关联": ("five_elements_reason", "state_query", "knowledge_retrieve"),
    "应答组织": ("report_search", "state_query", "knowledge_retrieve"),
}


def run_tools(question_type: str, *, search_query: str, state_key: str,
              report_md: str, context: dict[str, Any], knowledge: str,
              trace_dir: str | Path | None = None, target_id: str = "",
              elements: list[str] | None = None,
              top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """按问题类型执行写死的工具序列（序列之外不调用，spec 2.2/3.1 红线 3）。"""
    sequence = TOOL_SEQUENCES.get(question_type, ("report_search", "knowledge_retrieve"))
    states = (context.get("linkage") or {}).get("states") or []
    results: dict[str, Any] = {}
    for tool in sequence:
        if tool == "report_search":
            results[tool] = report_search(report_md, search_query, top_k)
        elif tool == "state_query":
            results[tool] = state_query(states, state_key)
        elif tool == "knowledge_retrieve":
            results[tool] = knowledge_retrieve(knowledge, search_query or state_key, top_k)
        elif tool == "reason_chain":
            results[tool] = reason_chain(trace_dir, target_id or state_key) if trace_dir else []
        elif tool == "five_elements_reason":
            results[tool] = five_elements_reason(elements or [])
        elif tool == "intervention_query":
            results[tool] = intervention_query(knowledge, search_query or state_key, top_k)
    return results


def render_tool_results(results: dict[str, list[dict[str, Any]]]) -> str:
    """工具结果 → prompt 文本块；全空时显式说明无命中（防模型装作检索过）。"""
    blocks: list[str] = []
    titles = {"report_search": "报告检索", "state_query": "状态查询",
              "knowledge_retrieve": "知识库检索", "reason_chain": "推导链",
              "five_elements_reason": "五行推理", "intervention_query": "方案检索"}
    for tool, hits in results.items():
        if not hits:
            continue
        if tool == "reason_chain":
            lines = ["### 推导链（信号 → 失衡 → 状态 → 议题）"]
            for node in hits:
                items = "；".join(
                    str(it.get("text") or it.get("name") or it.get("state_id") or it.get("topic") or it)
                    for it in node["items"])
                lines.append(f"- **{node['layer']}**：{items}")
            blocks.append("\n".join(lines))
            continue
        if tool == "five_elements_reason":
            blocks.append(f"### 五行推理\n- {hits['relation']}｜依据：{hits['basis']}（口径：{hits['source']}）")
            continue
        lines = [f"### {titles.get(tool, tool)}"]
        for h in hits:
            if tool == "state_query":
                lines.append(f"- state_id={h.get('state_id')} 层级={h.get('level')} "
                             f"置信度={h.get('confidence')} 证据链={h.get('source_observation_ids')}\n  {h}")
            else:
                anchor = f"（{h['anchor']}）" if h.get("anchor") else ""
                ids = f" 规则ID：{'/'.join(h['rule_ids'])}" if h.get("rule_ids") else ""
                lines.append(f"-{anchor} {h['text']}{ids}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
