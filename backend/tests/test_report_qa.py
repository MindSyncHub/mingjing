import json

import pytest

from app.core.guard import GuardResult, audit_output
from app.workflows.report_qa import agent as qa


def _make_run(tmp_path, report_id="R-20260101T000000Z-abc123"):
    run_dir = tmp_path / report_id
    run_dir.mkdir()
    (run_dir / "report.md").write_text("报告正文：安全感不足。", encoding="utf-8")
    (run_dir / "context.json").write_text(json.dumps({"report_id": report_id, "linkage": {
        "five_elements": [], "imbalances": [],
        "states": [{"state_id": "S-002", "level": "core", "claim_id": "C-001",
                    "source_observation_ids": ["O-001"], "knowledge_rule_refs": ["S-002 安全感不足"],
                    "confidence": 0.8, "status": "accepted"}],
        "topics": [],
    }}, ensure_ascii=False), encoding="utf-8")
    (run_dir / "claims.json").write_text(json.dumps({"claims": [{
        "claim_id": "C-001", "claim_type": "state_hypothesis", "status": "accepted",
        "knowledge_rule_refs": ["S-002 安全感不足"], "source_observation_ids": ["V-001"],
        "text": "安全感不足为核心层状态", "confidence": 0.8,
    }, {
        "claim_id": "C-900", "claim_type": "visual_observation", "status": "accepted",
        "knowledge_rule_refs": [], "source_observation_ids": ["V-001"],
        "text": "中心星形区呈红色", "confidence": 0.95,
    }]}, ensure_ascii=False), encoding="utf-8")
    (run_dir / "observations.json").write_text(json.dumps({
        "observations": [{"observation_id": "V-001", "kind": "color_block", "ring": "内圈"}],
    }, ensure_ascii=False), encoding="utf-8")
    (run_dir / "hypotheses.json").write_text(json.dumps({
        "five_elements": [],
        "imbalance_hypotheses": [{"name": "火乘金", "cause_element": "火", "result_element": "金",
                                  "support_observation_ids": ["V-001"]}],
        "state_hypotheses": [{"state_id": "S-002", "level": "core",
                              "support_observation_ids": ["V-001"], "imbalance_ref": "火乘金",
                              "knowledge_refs": ["S-002 安全感不足"]}],
        "topic_hypotheses": [{"topic": "配得感", "support_observation_ids": ["V-001"],
                              "knowledge_refs": ["T-01"], "confidence": 0.7}],
    }, ensure_ascii=False), encoding="utf-8")
    (run_dir / "analysis.md").write_text(
        "# 画面理解（Kimi）\n\n- [V-001] 内圈：中心为红色星形；区域：画面中心；置信度：0.95\n",
        encoding="utf-8")
    return run_dir


def test_qa_crisis_blocked(tmp_path):
    result = qa.answer_question(report_id="x", user_question="我不想活了", runs_root=tmp_path)
    assert result["blocked"] is True
    assert result["category"] == "crisis"


def test_qa_invalid_report_id_raises(tmp_path):
    with pytest.raises(ValueError):
        qa.answer_question(report_id="missing", user_question="安全感不足是什么意思？", runs_root=tmp_path)


def test_qa_normal_answer(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("知识库文本", ["docs/ontology.md"]))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    monkeypatch.setattr(qa, "_classify", lambda question, config: ("细节追问", 0.9, "", "", "", []))
    monkeypatch.setattr(qa, "_generate_with_safety",
                        lambda *a, **k: ("安全感不足指内在缺乏稳定感。",
                                         [{"knowledge_rule_ref": "S-002 安全感不足", "claim_id": "C-001", "quote": "报告正文"}],
                                         False))
    result = qa.answer_question(report_id=run_dir.name, user_question="安全感不足是什么意思？", runs_root=tmp_path)
    assert result["question_type"] == "细节追问"
    assert "安全感不足" in result["answer"]
    assert result["sources"][0]["knowledge_rule_ref"] == "S-002 安全感不足"
    assert result["safety_level"] == "L1"


def test_qa_reply_prep_adds_caveat(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    monkeypatch.setattr(qa, "_classify", lambda question, config: ("应答组织", 0.8, "", "", "", []))
    monkeypatch.setattr(qa, "_generate_with_safety", lambda *a, **k: ("回应素材", [], False))
    result = qa.answer_question(report_id=run_dir.name, user_question="我的来访者问：水多火灭是什么意思？",
                                scenario="reply_prep", runs_root=tmp_path)
    assert result["safety_level"] == "L2"
    assert "能量层面的参考" in result["caveat"]

# ---------- 危机用例（spec 4.2-2）：疗愈师转述来访者危机原话 → 提示个案风险，不拦截 ----------

def test_qa_crisis_transfer_case_risk(tmp_path):
    result = qa.answer_question(report_id="x", user_question="来访者说她最近不想活了，怎么办",
                                runs_root=tmp_path)
    # 转述危机原话：本轮不做常规回答，但区别于直接危机——标记为个案风险提示
    assert result["blocked"] is True
    assert result["category"] == "crisis_case_risk"
    assert "个案风险" in result["message"]
    assert "answer" not in result


# ---------- 输入拦截用例（spec 4.2-3）：医学/法律财务/恶意/严重心理 ----------

@pytest.mark.parametrize("question,category", [
    ("我是不是得了抑郁症？要不要开始吃药", "medical"),
    ("我和前夫有债务纠纷，该不该起诉他", "legal_financial"),
    ("傻屄吧你", "malicious"),
    ("我怀疑自己精神分裂了，最近有幻听", "severe_psych"),
])
def test_qa_input_blocked_categories(tmp_path, question, category):
    result = qa.answer_question(report_id="x", user_question=question, runs_root=tmp_path)
    assert result["blocked"] is True
    assert result["category"] == category
    assert "answer" not in result


def test_qa_unknown_scenario_raises(tmp_path):
    with pytest.raises(ValueError):
        qa.answer_question(report_id="x", user_question="问题", scenario="bad", runs_root=tmp_path)


# ---------- 输出审核用例（spec 4.2-4）：五类违规全部被改写 ----------

@pytest.mark.parametrize("text,pattern", [
    ("你有抑郁症，需要重视", "不是诊断"),
    ("你一定会好起来的，保证有效", "可能"),
    ("所有来访者都会永远依赖疗愈师", "大多数"),
    ("你不应该这么想，你错了", "或许可以考虑"),
    ("你应该分手，赶紧辞职", "不替你作决定"),
])
def test_audit_output_rewrites_violations(text, pattern):
    result = audit_output(text, "L2")
    assert result.blocked is True
    assert result.rewritten is not None
    assert pattern in result.rewritten


def test_audit_output_clean_text_passes():
    result = audit_output("安全感不足可能与早年经历有关，往往值得关注。", "L2")
    assert result.blocked is False


def test_qa_safety_loop_accepts_rewritten(tmp_path, monkeypatch):
    monkeypatch.setattr(qa, "_generate",
                        lambda *a, **k: ("你一定会好的，保证没问题", [], False))
    answer, sources, is_beyond = qa._generate_with_safety(
        "问题", "细节追问", "reply_prep", "报告", {}, [], "", {})
    assert "保证" not in answer
    assert "可能" in answer


def test_qa_safety_loop_degrades_after_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(qa, "_generate", lambda *a, **k: ("违规回答", [], False))
    monkeypatch.setattr(qa, "audit_output", lambda text, level: GuardResult(blocked=True, violations=["x"]))
    answer, sources, is_beyond = qa._generate_with_safety(
        "问题", "细节追问", "advisor", "报告", {}, [], "", {})
    assert answer == qa._DEGRADE_ANSWER
    assert sources == []


# ---------- 边界用例（spec 4.2-5）：超范围内容带标注 ----------

def test_qa_beyond_report_flagged(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    monkeypatch.setattr(qa, "_classify", lambda question, config: ("深度探讨", 0.7, "", "", "", []))
    monkeypatch.setattr(qa, "_generate_with_safety", lambda *a, **k: ("延伸内容", [], True))
    result = qa.answer_question(report_id=run_dir.name, user_question="这和她的婚姻关系有关吗？",
                                runs_root=tmp_path)
    assert result["boundary_note"] == "这是延伸探讨，不是报告结论"


# ---------- 锚定用例（spec 4.2-6）：来源标注；空来源时从 claims 回退 ----------

def test_qa_sources_fallback_to_claims(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    monkeypatch.setattr(qa, "_classify", lambda question, config: ("细节追问", 0.9, "", "", "", []))
    # mock 底层生成（返回空来源），走真实 _generate_with_safety 验证 claims 回退
    monkeypatch.setattr(qa, "_generate", lambda *a, **k: ("答案", [], False))
    result = qa.answer_question(report_id=run_dir.name, user_question="安全感不足是什么意思？",
                                runs_root=tmp_path)
    assert result["sources"] == [{"knowledge_rule_ref": "S-002 安全感不足"}]


# ---------- 问题分类兜底：LLM 返回非法类型/置信度时按细节追问处理 ----------

def test_classify_falls_back_on_bad_output(monkeypatch):
    monkeypatch.setattr(qa, "_direct_chat", lambda *a, **k: ('{"question_type":"胡说八道","confidence":"abc"}', {}))
    qt, conf, search_query, state_key, target_id, elements = qa._classify(
        "问题", {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    assert qt == "细节追问"
    assert conf == 0.5
    assert search_query == "" and state_key == "" and target_id == "" and elements == []


def test_classify_parses_valid_output(monkeypatch):
    monkeypatch.setattr(qa, "_direct_chat", lambda *a, **k: (
        '{"question_type":"跨议题关联","confidence":0.87,'
        '"search_query":"财富 亲密","state_key":"S-002",'
        '"target_id":"火乘金","elements":["红","白"]}', {}))
    qt, conf, search_query, state_key, target_id, elements = qa._classify(
        "财富和亲密有关系吗？", {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    assert qt == "跨议题关联"
    assert conf == 0.87
    assert search_query == "财富 亲密"
    assert state_key == "S-002"
    assert target_id == "火乘金"
    assert elements == ["红", "白"]

@pytest.fixture(autouse=True)
def _reset_kb_cache():
    qa._KNOWLEDGE_CACHE = None
    yield
    qa._KNOWLEDGE_CACHE = None


# ---------- 多轮对话（spec 2.3）：历史注入 / 超窗滚动摘要 / 轮次硬限 ----------

def _chat_capture(monkeypatch):
    """捕获 _direct_chat 调用：分类按 JSON 返回，生成返回固定答案，摘要返回固定文本。"""
    calls = {"generate": [], "summarize": []}

    def fake_chat(*, url, key, model, messages, label, json_mode, temperature):
        if label == "QA 问题分类":
            return ('{"question_type":"细节追问","confidence":0.9}', {})
        if label == "QA 历史摘要":
            calls["summarize"].append(messages[0]["content"])
            return ("早前讨论了五行分布与核心状态。", {})
        calls["generate"].append(messages[0]["content"])
        return ('{"answer":"回答","sources":[],"is_beyond_report":false}', {})

    return calls, fake_chat


def _history(rounds, start=1):
    msgs = []
    for i in range(start, start + rounds):
        msgs.append({"role": "user", "content": f"第{i}个问题"})
        msgs.append({"role": "assistant", "content": f"第{i}个回答"})
    return msgs


def _base_answer_call(tmp_path, monkeypatch, conversation_history):
    run_dir = _make_run(tmp_path)
    calls, fake_chat = _chat_capture(monkeypatch)
    monkeypatch.setattr(qa, "_direct_chat", fake_chat)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    result = qa.answer_question(report_id=run_dir.name, user_question="新问题",
                                conversation_history=conversation_history, runs_root=tmp_path)
    return result, calls


def test_history_injected_into_prompt(tmp_path, monkeypatch):
    result, calls = _base_answer_call(tmp_path, monkeypatch, _history(2))
    assert result["answer"] == "回答"
    prompt = calls["generate"][0]
    assert "【对话历史】" in prompt
    assert "第1个问题" in prompt and "第1个回答" in prompt
    assert calls["summarize"] == []  # 未超窗不触发摘要


def test_history_overflow_rolls_summary(tmp_path, monkeypatch):
    result, calls = _base_answer_call(tmp_path, monkeypatch, _history(7))  # 14 条 > 10 条窗口
    assert result["answer"] == "回答"
    assert len(calls["summarize"]) == 1  # 滚动摘要被调用
    prompt = calls["generate"][0]
    assert "【早前对话摘要】早前讨论了五行分布与核心状态。" in prompt
    assert "第7个问题" in prompt  # 窗口内原文保留（最近 5 轮）


def test_no_history_no_block(tmp_path, monkeypatch):
    result, calls = _base_answer_call(tmp_path, monkeypatch, None)
    assert "【对话历史】" not in calls["generate"][0]


def test_round_limit_notice(tmp_path, monkeypatch):
    history = _history(30)  # advisor 上限 30 轮
    result, _ = _base_answer_call(tmp_path, monkeypatch, history)
    assert result.get("round_limit") is True
    assert "建议开启新会话" in result["answer"]


def test_round_limit_not_hit_below_cap(tmp_path, monkeypatch):
    result, _ = _base_answer_call(tmp_path, monkeypatch, _history(5))
    assert "round_limit" not in result

# ---------- 工具化检索（spec 3.4 契约；一期 3 工具）----------

from app.workflows.report_qa import tools as qt  # noqa: E402


REPORT_SAMPLE = """# 解读报告

## 五行分布
火元素主导，水元素偏弱。

## 核心状态
### 安全感不足（S-002）
核心层状态，源自早年经历，置信度 0.8。
"""


def test_report_search_returns_anchor_and_text():
    hits = qt.report_search(REPORT_SAMPLE, "安全感不足")
    assert hits, "应命中状态段落"
    assert hits[0]["anchor"] == "安全感不足（S-002）"
    assert "核心层状态" in hits[0]["text"]


def test_report_search_no_match_returns_empty():
    assert qt.report_search(REPORT_SAMPLE, "量子物理") == []


def test_state_query_by_id_and_by_name():
    states = [{"state_id": "S-002", "name": "安全感不足", "level": "core",
               "knowledge_rule_refs": ["S-002 安全感不足"], "confidence": 0.8}]
    assert qt.state_query(states, "S-002")[0]["state_id"] == "S-002"
    assert qt.state_query(states, "安全感不足")[0]["level"] == "core"
    assert qt.state_query(states, "不存在的") == []


KNOWLEDGE_SAMPLE = """# 五行生克

## 火乘金
C-11 规则：火元素过强压制金元素，表现为边界感弱。

## 冥想方案
T-05 方案： grounding 冥想，每日 10 分钟。
"""


def test_knowledge_retrieve_finds_rule_ids():
    hits = qt.knowledge_retrieve(KNOWLEDGE_SAMPLE, "火乘金")
    assert hits, "应命中生克条目"
    assert "C-11" in hits[0]["rule_ids"]


def test_knowledge_retrieve_miss_finds_nothing():
    assert qt.knowledge_retrieve(KNOWLEDGE_SAMPLE, "占星") == []


def test_run_tools_respects_sequence_and_extras():
    ctx = {"linkage": {"states": [{"state_id": "S-002", "name": "安全感不足"}]}}
    results = qt.run_tools("细节追问", search_query="安全感不足", state_key="S-002",
                           report_md=REPORT_SAMPLE, context=ctx, knowledge=KNOWLEDGE_SAMPLE)
    assert list(results.keys()) == ["report_search", "state_query", "knowledge_retrieve"]
    results = qt.run_tools("方案细化", search_query="冥想", state_key="",
                           report_md=REPORT_SAMPLE, context=ctx, knowledge=KNOWLEDGE_SAMPLE)
    assert list(results.keys()) == ["intervention_query", "knowledge_retrieve"]  # spec 2.2 序列


def test_render_tool_results_empty_says_so():
    assert "无命中" in qt.render_tool_results({"report_search": []}) or qt.render_tool_results({"report_search": []}) == ""


def test_answer_uses_retrieval_block(tmp_path, monkeypatch):
    """端到端：分类提取参数 → 工具执行 → 生成 prompt 含检索结果而非全量知识库。"""
    run_dir = _make_run(tmp_path)
    calls, fake_chat = _chat_capture(monkeypatch)

    def classify_chat(*, url, key, model, messages, label, json_mode, temperature):
        if label == "QA 问题分类":
            return ('{"question_type":"细节追问","confidence":0.9,'
                    '"search_query":"安全感不足","state_key":"S-002"}', {})
        calls["generate"].append(messages[0]["content"])
        return ('{"answer":"回答","sources":[],"is_beyond_report":false}', {})

    monkeypatch.setattr(qa, "_direct_chat", classify_chat)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: (KNOWLEDGE_SAMPLE, []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    result = qa.answer_question(report_id=run_dir.name, user_question="安全感不足是什么意思？", runs_root=tmp_path)
    assert result["answer"] == "回答"
    prompt = calls["generate"][0]
    assert "【检索结果】" in prompt
    assert "火乘金" not in prompt  # 未命中条目不进 prompt（防全量直注回潮）

# ---------- 轮次落盘（spec 2.3 / D-094）：一问一文件，护栏拒绝同等待遇 ----------

import json as _json  # noqa: E402
from pathlib import Path  # noqa: E402


def _read_turn(run_dir, n):
    return _json.loads((run_dir / "qa" / f"turn-{n:04d}.json").read_text(encoding="utf-8"))


def test_turn_persisted_with_fields(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    calls, fake_chat = _chat_capture(monkeypatch)
    monkeypatch.setattr(qa, "_direct_chat", fake_chat)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    result = qa.answer_question(report_id=run_dir.name, user_question="问题一", runs_root=tmp_path)
    turn = _read_turn(run_dir, 1)
    assert turn["question"] == "问题一"
    assert turn["scenario"] == "advisor"
    assert turn["question_type"] == "细节追问"
    assert turn["answer"] == result["answer"]
    assert turn["audit"] == "pass"
    assert turn["timestamp"] and turn["turn"] == 1


def test_turns_numbered_sequentially(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    calls, fake_chat = _chat_capture(monkeypatch)
    monkeypatch.setattr(qa, "_direct_chat", fake_chat)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    qa.answer_question(report_id=run_dir.name, user_question="问题一", runs_root=tmp_path)
    qa.answer_question(report_id=run_dir.name, user_question="问题二", runs_root=tmp_path)
    assert _read_turn(run_dir, 2)["question"] == "问题二"


def test_blocked_turn_persisted_as_formal_answer(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    result = qa.answer_question(report_id=run_dir.name, user_question="我该吃药吗？",
                                runs_root=tmp_path)
    assert result["blocked"] is True
    turn = _read_turn(run_dir, 1)
    assert turn["audit"] == "blocked"
    assert turn["blocked_category"] == "medical"
    assert turn["answer"] == result["message"]  # 拒绝落盘为正式回答，历史可见


def test_blocked_turn_skipped_when_run_missing(tmp_path):
    # report_id 无效且目录不存在：不落盘也不报错（拦截照常返回）
    result = qa.answer_question(report_id="missing", user_question="我该吃药吗？", runs_root=tmp_path)
    assert result["blocked"] is True
    assert not (tmp_path / "missing" / "qa").exists()


def test_reply_prep_turn_includes_caveat(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    calls, fake_chat = _chat_capture(monkeypatch)
    monkeypatch.setattr(qa, "_direct_chat", fake_chat)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    qa.answer_question(report_id=run_dir.name, user_question="来访者问报告结论",
                       scenario="reply_prep", runs_root=tmp_path)
    turn = _read_turn(run_dir, 1)
    assert turn["safety_level"] == "L2"
    assert turn["caveat"].startswith("能量层面的参考")

# ---------- 回答后操作（spec 2.5）：再生成一版 / 指错重分类 ----------

def _qa_env(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    calls, fake_chat = _chat_capture(monkeypatch)
    monkeypatch.setattr(qa, "_direct_chat", fake_chat)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    return run_dir, calls


def test_regenerate_reuses_classification_and_injects_supplement(tmp_path, monkeypatch):
    run_dir, calls = _qa_env(tmp_path, monkeypatch)
    qa.answer_question(report_id=run_dir.name, user_question="安全感不足是什么意思？", runs_root=tmp_path)
    classify_calls = len(calls["generate"])  # 分类器也在 _direct_chat 流里，这里只看生成 prompt 数
    qa.answer_question(report_id=run_dir.name, user_question="安全感不足是什么意思？",
                       action="regenerate", supplement="更通俗一点", runs_root=tmp_path)
    # 两轮各有一次生成；补充要求必须出现在第二轮生成 prompt 里
    assert len(calls["generate"]) == classify_calls + 1
    assert "更通俗一点" in calls["generate"][-1]
    turn = _read_turn(run_dir, 2)
    assert turn["action"] == "regenerate"
    assert turn["supplement"] == "更通俗一点"
    assert turn["question_type"] == _read_turn(run_dir, 1)["question_type"]  # 分类沿用


def test_regenerate_falls_back_to_classify_without_history(tmp_path, monkeypatch):
    run_dir, calls = _qa_env(tmp_path, monkeypatch)
    qa.answer_question(report_id=run_dir.name, user_question="全新问题",
                       action="regenerate", runs_root=tmp_path)
    turn = _read_turn(run_dir, 1)
    assert turn["action"] == "regenerate"  # 操作本身照常留痕
    assert turn["question_type"] == "细节追问"  # 无历史 → 重新分类（mock 分类器返回值）


def test_reclassify_overrides_type_with_audit_trail(tmp_path, monkeypatch):
    run_dir, calls = _qa_env(tmp_path, monkeypatch)
    qa.answer_question(report_id=run_dir.name, user_question="为什么我会有安全感不足？",
                       action="reclassify", override_type="深度探讨", runs_root=tmp_path)
    turn = _read_turn(run_dir, 1)
    assert turn["question_type"] == "深度探讨"
    assert turn["action"] == "reclassify"
    assert turn["override_type"] == "深度探讨"
    assert turn["human_corrected"] is True
    assert turn["confidence"] == 1.0


def test_reclassify_rejects_bad_override(tmp_path, monkeypatch):
    run_dir, _ = _qa_env(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        qa.answer_question(report_id=run_dir.name, user_question="问题",
                           action="reclassify", override_type="胡说", runs_root=tmp_path)
    with pytest.raises(ValueError):
        qa.answer_question(report_id=run_dir.name, user_question="问题",
                           action="reclassify", runs_root=tmp_path)


def test_unknown_action_rejected(tmp_path, monkeypatch):
    run_dir, _ = _qa_env(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        qa.answer_question(report_id=run_dir.name, user_question="问题",
                           action="飞升", runs_root=tmp_path)


def test_followup_action_counts_toward_round_limit(tmp_path, monkeypatch):
    run_dir, calls = _qa_env(tmp_path, monkeypatch)
    # 预置 15 个已落盘轮次 = reply_prep 上限
    for i in range(15):
        qa.answer_question(report_id=run_dir.name, user_question=f"铺垫{i}",
                           scenario="reply_prep", runs_root=tmp_path)
    result = qa.answer_question(report_id=run_dir.name, user_question="铺垫0",
                                scenario="reply_prep", action="regenerate", runs_root=tmp_path)
    assert result.get("round_limit") is True

# ---------- 剩余三工具（spec 3.4）：reason_chain / five_elements_reason / intervention_query ----------


def test_five_elements_reason_cycles_and_aliases():
    assert qt.five_elements_reason(["火", "金"])["relation"] == "火克金"
    assert qt.five_elements_reason(["木", "火"])["relation"] == "木生火"
    assert qt.five_elements_reason(["金", "土"])["relation"] == "土生金"  # 被生方向
    assert qt.five_elements_reason(["水", "水"])["relation"] == "比和"
    assert qt.five_elements_reason(["红", "白"])["relation"] == "火克金"  # 颜色归一化
    assert qt.five_elements_reason(["星形", "圆"])["relation"] == "火克金"  # 形状归一化
    assert qt.five_elements_reason(["火星", ""]) is None
    assert qt.five_elements_reason(["xyz", "火"]) is None  # 不可归一化 → None，走回退


def test_reason_chain_by_state_id():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        run_dir = _make_run(Path(td))
        chain = qt.reason_chain(run_dir, "S-002")
    layers = [node["layer"] for node in chain]
    assert layers == ["信号", "失衡", "状态", "议题"]
    state_node = chain[2]["items"][0]
    assert state_node["state_id"] == "S-002" and state_node["level"] == "core"


def test_reason_chain_by_imbalance_name():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        run_dir = _make_run(Path(td))
        chain = qt.reason_chain(run_dir, "火乘金")
    assert chain[0]["layer"] == "信号" and chain[0]["items"][0]["id"] == "V-001"
    assert chain[1]["items"][0]["cause"] == "火"


def test_reason_chain_missing_target_returns_empty(tmp_path):
    assert qt.reason_chain(tmp_path, "S-999") == []
    assert qt.reason_chain(tmp_path, "") == []


def test_intervention_query_filters_non_intervention():
    knowledge = """# 五行生克

## 火乘金
C-11 规则：火元素过强压制金元素。

## grounding 冥想
T-05 方案：每日 10 分钟，专注呼吸。

## 颜色含义
C-03 规则：红色代表能量外放。
"""
    hits = qt.intervention_query(knowledge, "冥想")
    assert hits and all("T-" in "/".join(h["rule_ids"]) or "方案" in h["text"] or "冥想" in h["text"]
                        for h in hits)
    assert not any("C-11" in "/".join(h["rule_ids"]) for h in hits)  # 非方案内容被过滤


def test_full_sequences_per_spec():
    ctx = {"linkage": {"states": []}}
    for qtype, seq in qt.TOOL_SEQUENCES.items():
        results = qt.run_tools(qtype, search_query="x", state_key="",
                               report_md=REPORT_SAMPLE, context=ctx,
                               knowledge=KNOWLEDGE_SAMPLE, trace_dir=None)
        assert list(results.keys()) == list(seq), qtype
    # 深度探讨必须含 reason_chain 位；跨议题关联必须以 five_elements_reason 开头
    assert "reason_chain" in qt.TOOL_SEQUENCES["深度探讨"]
    assert qt.TOOL_SEQUENCES["跨议题关联"][0] == "five_elements_reason"
    assert qt.TOOL_SEQUENCES["方案细化"][0] == "intervention_query"


def test_render_new_tool_shapes():
    chain = [{"layer": "信号", "items": [{"id": "V-001", "text": "红色星形"}]},
             {"layer": "状态", "items": [{"state_id": "S-002", "level": "core"}]}]
    text = qt.render_tool_results({"reason_chain": chain,
                                   "five_elements_reason": {"relation": "火克金", "basis": "相克环：火克金",
                                                            "source": "mandala-5e"}})
    assert "推导链" in text and "红色星形" in text and "S-002" in text
    assert "火克金" in text


def test_deep_dive_end_to_end_with_reason_chain(tmp_path, monkeypatch):
    """深度探讨端到端：分类给 target_id → 推导链进生成 prompt。"""
    run_dir = _make_run(tmp_path)
    calls, _ = _chat_capture(monkeypatch)

    def classify_chat(*, url, key, model, messages, label, json_mode, temperature):
        if label == "QA 问题分类":
            return ('{"question_type":"深度探讨","confidence":0.9,"search_query":"安全感不足",'
                    '"state_key":"S-002","target_id":"S-002","elements":[]}', {})
        calls["generate"].append(messages[0]["content"])
        return ('{"answer":"回答","sources":[],"is_beyond_report":false}', {})

    monkeypatch.setattr(qa, "_direct_chat", classify_chat)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    result = qa.answer_question(report_id=run_dir.name, user_question="为什么会有安全感不足？",
                                runs_root=tmp_path)
    assert result["answer"] == "回答"
    prompt = calls["generate"][0]
    assert "推导链" in prompt and "V-001" in prompt and "火乘金" in prompt and "配得感" in prompt

# ---------- 新 run 结构兼容（无 context.json 时从 hypotheses.json 兜底）+ 知识库缓存 ----------


def _env_no_context(tmp_path, monkeypatch):
    """造一份无 context.json 的新结构 run（模拟并行窗口新产物）。"""
    run_dir = _make_run(tmp_path)
    (run_dir / "context.json").unlink()
    calls, fake_chat = _chat_capture(monkeypatch)
    monkeypatch.setattr(qa, "_direct_chat", fake_chat)
    monkeypatch.setattr(qa, "_load_knowledge", lambda: ("", []))
    monkeypatch.setattr(qa, "_api_config", lambda: {"deepseek_key": "k", "deepseek_url": "u", "deepseek_model": "m"})
    return run_dir, calls


def test_answer_works_without_context_json(tmp_path, monkeypatch):
    run_dir, calls = _env_no_context(tmp_path, monkeypatch)

    def classify_chat(*, url, key, model, messages, label, json_mode, temperature):
        if label == "QA 问题分类":
            return ('{"question_type":"细节追问","confidence":0.9,"search_query":"安全感不足",'
                    '"state_key":"S-002","target_id":"","elements":[]}', {})
        calls["generate"].append(messages[0]["content"])
        return ('{"answer":"回答","sources":[],"is_beyond_report":false}', {})

    monkeypatch.setattr(qa, "_direct_chat", classify_chat)
    result = qa.answer_question(report_id=run_dir.name, user_question="安全感不足是什么意思？",
                                runs_root=tmp_path)
    assert result["answer"] == "回答"
    # 兜底链路：state_query 仍能从 hypotheses.json 解析出 S-002
    assert "S-002" in calls["generate"][0]
    turn = _read_turn(run_dir, 1)
    assert turn["question_type"] == "细节追问"


def test_knowledge_cache_avoids_reload(tmp_path, monkeypatch):
    calls = {"n": 0}

    def counting_load():
        calls["n"] += 1
        return ("", [])

    monkeypatch.setattr(qa, "_load_knowledge", counting_load)
    qa._KNOWLEDGE_CACHE = None
    qa._knowledge_with_cache()
    qa._knowledge_with_cache()
    qa._knowledge_with_cache()
    assert calls["n"] == 1  # 三次调用只读一次盘

# ---------- 生成容错（spec 2.4：JSON 解析失败 Retry 后降级）----------


def test_generate_json_error_retries_then_degrades(tmp_path, monkeypatch):
    attempts = {"n": 0}

    def flaky_generate(*a, **k):
        attempts["n"] += 1
        raise ValueError("QA 生成 返回不是合法 JSON")

    monkeypatch.setattr(qa, "_generate", flaky_generate)
    answer, sources, is_beyond = qa._generate_with_safety(
        "问题", "细节追问", "advisor", "报告", {}, [], "", {})
    assert attempts["n"] == 3
    assert answer == qa._DEGRADE_ANSWER


def test_generate_recovers_on_second_attempt(tmp_path, monkeypatch):
    attempts = {"n": 0}

    def flaky_generate(*a, **k):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ValueError("bad json")
        return ("恢复后的回答", [], False)

    monkeypatch.setattr(qa, "_generate", flaky_generate)
    answer, _, _ = qa._generate_with_safety("问题", "细节追问", "advisor", "报告", {}, [], "", {})
    assert answer == "恢复后的回答"
    assert attempts["n"] == 2



class TestListTurns:
    """问答历史回读（spec 2.6）。"""

    def test_no_qa_dir_returns_empty(self, tmp_path):
        run_dir = _make_run(tmp_path)
        assert qa.list_turns(report_id=run_dir.name, runs_root=tmp_path) == []

    def test_invalid_report_id_returns_empty(self, tmp_path):
        assert qa.list_turns(report_id="R-missing", runs_root=tmp_path) == []

    def test_returns_turns_in_order(self, tmp_path):
        run_dir = _make_run(tmp_path)
        qa_dir = run_dir / "qa"
        qa_dir.mkdir()
        for no, q in ((2, "第二个问题"), (1, "第一个问题")):
            (qa_dir / f"turn-{no:04d}.json").write_text(json.dumps(
                {"turn": no, "question": q, "answer": "答", "audit": "pass"},
                ensure_ascii=False), encoding="utf-8")
        turns = qa.list_turns(report_id=run_dir.name, runs_root=tmp_path)
        assert [t["turn"] for t in turns] == [1, 2]
        assert turns[0]["question"] == "第一个问题"

    def test_corrupt_file_skipped(self, tmp_path):
        run_dir = _make_run(tmp_path)
        qa_dir = run_dir / "qa"
        qa_dir.mkdir()
        (qa_dir / "turn-0001.json").write_text("{非法 JSON", encoding="utf-8")
        (qa_dir / "turn-0002.json").write_text(json.dumps(
            {"turn": 2, "question": "问", "answer": "答"}, ensure_ascii=False), encoding="utf-8")
        turns = qa.list_turns(report_id=run_dir.name, runs_root=tmp_path)
        assert [t["turn"] for t in turns] == [2]

    def test_get_turns_endpoint(self, tmp_path, monkeypatch):
        from app.main import app
        from fastapi.testclient import TestClient
        monkeypatch.setattr("app.main.list_turns",
                            lambda report_id: qa.list_turns(report_id=report_id, runs_root=tmp_path))
        run_dir = _make_run(tmp_path)
        qa_dir = run_dir / "qa"
        qa_dir.mkdir()
        (qa_dir / "turn-0001.json").write_text(json.dumps(
            {"turn": 1, "question": "问", "answer": "答", "audit": "pass"},
            ensure_ascii=False), encoding="utf-8")
        resp = TestClient(app).get("/report-qa/turns", params={"report_id": run_dir.name})
        assert resp.status_code == 200
        body = resp.json()
        assert body["report_id"] == run_dir.name
        assert len(body["turns"]) == 1 and body["turns"][0]["turn"] == 1

    def test_get_turns_endpoint_empty(self, tmp_path, monkeypatch):
        from app.main import app
        from fastapi.testclient import TestClient
        monkeypatch.setattr("app.main.list_turns",
                            lambda report_id: qa.list_turns(report_id=report_id, runs_root=tmp_path))
        resp = TestClient(app).get("/report-qa/turns", params={"report_id": "R-none"})
        assert resp.status_code == 200 and resp.json()["turns"] == []

    def test_get_turns_endpoint_missing_param(self):
        from app.main import app
        from fastapi.testclient import TestClient
        resp = TestClient(app).get("/report-qa/turns", params={"report_id": "  "})
        assert resp.status_code == 422
