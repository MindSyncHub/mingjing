"""D-111 本地工作台 UI：ui_api 纯函数部分测试（spec: docs/specs/ui-v1.md 验收层 UI-003/004/007）。

只测不依赖 cv2/模型调用的部分：列表扫描、g1 摘要、详情、md 保存+重渲、路径安全。
"""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.ui_api import (_g1_summary, get_report_detail, get_review, get_trace, list_reports,
                        re_render, report_image_path, save_report_md, upsert_review_item)

RUN_ID = "R-test-001abc"


def _write_run(run_dir: Path, g1: dict | None, with_html: bool = True, started_at: str = "2026-09-29T00:00:00+00:00") -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "report.md").write_text(
        "曼陀罗解读报告\n解读主题：测试\n\n**定调。** 内容。\n\n## 小节\n\n正文。\n\n"
        "以上是能量层面的参考，不是诊断，AI 是辅助工具，最终判断在疗愈师。\n", encoding="utf-8")
    if with_html:
        (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    meta = {"report_id": run_dir.name, "status": "completed",
            "started_at": started_at,
            "elapsed_ms": 100, "input": {"theme": "测试主题", "image_path": str(run_dir / "painting.jpg")},
            "models": {"vision": "kimi-k3", "text": "deepseek-chat"},
            "g1": g1, "token_usage": {}, "timings_ms": {}}
    (run_dir / "run.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def runs_root(tmp_path: Path) -> Path:
    g1_ok = {"passed": True, "accepted_claim_count": 10, "orphan_accepted_claims": [],
             "forbidden_phrases": [], "marker_line_evidence_claims": [],
             "pending_terms_used_in_body": [], "exemplar_copy_spans": [],
             "unanchored_statements": []}
    g1_flag = {"passed": True, "accepted_claim_count": 8, "orphan_accepted_claims": [],
               "forbidden_phrases": [], "marker_line_evidence_claims": [],
               "pending_terms_used_in_body": [], "exemplar_copy_spans": ["照搬片段原文"],
               "unanchored_statements": ["无证据的画面句"]}
    _write_run(tmp_path / "R-20260929T000000Z-aaaaaa", g1_flag,
               started_at="2026-09-29T00:00:00+00:00")
    _write_run(tmp_path / "R-20260929T010000Z-bbbbbb", g1_ok,
               started_at="2026-09-29T01:00:00+00:00")
    return tmp_path


def test_list_reports_sorted_desc_with_flags(runs_root):
    rows = list_reports(runs_root=runs_root)
    assert [r["report_id"] for r in rows] == ["R-20260929T010000Z-bbbbbb", "R-20260929T000000Z-aaaaaa"]
    older = rows[1]
    assert older["theme"] == "测试主题"
    assert older["g1"]["passed"] is True
    assert older["g1"]["needs_review"] is True  # 照搬+未锚定 >0 → 需复核
    assert older["g1"]["flags"]["exemplar_copy_spans"] == 1
    assert older["g1"]["flags"]["unanchored_statements"] == 1
    assert rows[0]["g1"]["needs_review"] is False


def test_list_reports_empty_dir(tmp_path):
    assert list_reports(runs_root=tmp_path) == []


def test_g1_summary_missing_g1():
    s = _g1_summary(None)
    assert s["passed"] is False and s["needs_review"] is True and s["flags"]["orphan_accepted_claims"] == 0


def test_get_report_detail(runs_root):
    d = get_report_detail("R-20260929T010000Z-bbbbbb", runs_root=runs_root)
    assert d["status"] == "completed"
    assert d["has_report_html"] and d["has_report_md"]
    assert "曼陀罗解读报告" in d["report_md"]
    assert d["models"]["vision"] == "kimi-k3"


@pytest.mark.parametrize("bad_id", ["", "no-such", "../etc", "a/b", "..", ".hidden"])
def test_get_run_dir_rejects_bad_ids(runs_root, bad_id):
    with pytest.raises(HTTPException) as exc:
        get_report_detail(bad_id, runs_root=runs_root)
    assert exc.value.status_code == 404


def test_save_report_md_renders_and_marks_edited(runs_root):
    rid = "R-20260929T010000Z-bbbbbb"
    new_md = "曼陀罗解读报告\n解读主题：改后\n\n**新定调。** 新内容。\n\n## 新小节\n\n新正文。\n"
    result = save_report_md(rid, new_md, runs_root=runs_root)
    assert result["saved"] is True
    assert result["render_ms"] < 10_000
    run_dir = runs_root / rid
    assert (run_dir / "report.md").read_text(encoding="utf-8") == new_md
    html = (run_dir / "report.html").read_text(encoding="utf-8")
    assert "<h1>曼陀罗解读报告</h1>" in html  # D-110 渲染真的跑了
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert meta["edited_at"]  # 编辑留痕


def test_save_report_md_rejects_blank(runs_root):
    with pytest.raises(HTTPException) as exc:
        save_report_md("R-20260929T010000Z-bbbbbb", "   \n", runs_root=runs_root)
    assert exc.value.status_code == 422


def test_re_render(runs_root):
    rid = "R-20260929T010000Z-bbbbbb"
    (runs_root / rid / "report.html").unlink()
    result = re_render(rid, runs_root=runs_root)
    assert result["render_ms"] < 10_000
    assert (runs_root / rid / "report.html").is_file()


def test_report_image_path(runs_root):
    rid = "R-20260929T010000Z-bbbbbb"
    img = runs_root / rid / "painting.jpg"
    img.write_bytes(b"\xff\xd8\xff")  # 假 JPEG 头，只验路径逻辑
    assert report_image_path(rid, runs_root=runs_root) == img


def _write_trace_artifacts(run_dir: Path) -> None:
    (run_dir / "perception.md").write_text("整体形制：圆形曼陀罗。", encoding="utf-8")
    (run_dir / "report.sourced.md").write_text("报告正文〔来源: C-900〕", encoding="utf-8")
    (run_dir / "observations.json").write_text(json.dumps(
        {"observations": [{"observation_id": "V-001", "ring": "整体", "kind": "structure",
                           "description": "圆形", "confidence": None}],
         "vision_observations": [{"raw": "x"}], "vision_ambiguities": ["模糊点"],
         "questions_for_healer": ["提问"]}, ensure_ascii=False), encoding="utf-8")
    (run_dir / "signals.json").write_text(json.dumps(
        {"blocks": [{"ring": "内圈", "color_raw": "黄", "shape_brief": "小圆",
                     "position": "中心", "quantity_tier": "主导"}],
         "structures": [{"s": 1}]}, ensure_ascii=False), encoding="utf-8")
    (run_dir / "hypotheses.json").write_text(json.dumps(
        {"direct_pattern_hits": [{"pattern_id": "D-04", "confidence": 0.75,
                                  "support_observation_ids": ["V-003"]}],
         "five_elements": [], "imbalance_hypotheses": [], "state_hypotheses": [],
         "topic_hypotheses": []}, ensure_ascii=False), encoding="utf-8")
    (run_dir / "claims.json").write_text(json.dumps(
        {"claims": [{"claim_id": "C-900", "claim_type": "visual_observation", "text": "圆形",
                     "status": "accepted", "source_observation_ids": ["V-001"]},
                    {"claim_id": "C-001", "claim_type": "state_hypothesis", "text": "成长受阻",
                     "status": "needs_human", "confidence": 0.5,
                     "needs_human_reason": "缺少画面观察"}]}, ensure_ascii=False), encoding="utf-8")


def test_get_trace_full_chain(runs_root):
    rid = "R-20260929T010000Z-bbbbbb"
    _write_trace_artifacts(runs_root / rid)
    t = get_trace(rid, runs_root=runs_root)
    assert "圆形曼陀罗" in t["perception_md"]
    assert len(t["observations"]) == 1 and t["observations"][0]["observation_id"] == "V-001"
    assert len(t["vision_observations"]) == 1 and len(t["ambiguities"]) == 1
    assert t["signals"]["blocks"][0]["color_raw"] == "黄"
    assert t["hypotheses"]["direct_pattern_hits"][0]["confidence"] == 0.75
    assert len(t["claims"]["accepted"]) == 1 and len(t["claims"]["needs_human"]) == 1
    assert t["claims"]["needs_human"][0]["needs_human_reason"]
    assert "〔来源: C-900〕" in t["report_sourced_md"]
    # g1 flags detail 从 run.json 透传（fixture 的 g1 全空列表）
    assert t["g1_flags_detail"]["exemplar_copy_spans"] == []


def test_get_trace_missing_files_tolerated(runs_root):
    rid = "R-20260929T000000Z-aaaaaa"  # 只有 run.json + report.md 的旧 run
    t = get_trace(rid, runs_root=runs_root)
    assert t["perception_md"] == "" and t["observations"] == []
    assert t["claims"] == {"accepted": [], "needs_human": []}
    assert t["report_sourced_md"] == ""


def test_review_roundtrip(runs_root):
    rid = "R-20260929T010000Z-bbbbbb"
    assert get_review(rid, runs_root=runs_root)["items"] == {}
    r = upsert_review_item(rid, "obs:V-001", True, "属实", runs_root=runs_root)
    assert r["entry"]["checked"] is True and r["entry"]["note"] == "属实"
    # 单独更新备注不动勾；单独更新勾不动备注
    r = upsert_review_item(rid, "obs:V-001", None, "改备注", runs_root=runs_root)
    assert r["entry"]["checked"] is True and r["entry"]["note"] == "改备注"
    r = upsert_review_item(rid, "obs:V-001", False, None, runs_root=runs_root)
    assert r["entry"]["checked"] is False and r["entry"]["note"] == "改备注"
    # 清掉备注 + 取消勾 → 条目删除
    upsert_review_item(rid, "obs:V-001", False, "", runs_root=runs_root)
    assert get_review(rid, runs_root=runs_root)["items"] == {}
    # general 总评注与各前缀
    upsert_review_item(rid, "general", None, "整体可信", runs_root=runs_root)
    upsert_review_item(rid, "hyp:direct_pattern_hits:D-04", None, "置信度存疑", runs_root=runs_root)
    upsert_review_item(rid, "flag:unanchored_statements:0", None, "删这句", runs_root=runs_root)
    items = get_review(rid, runs_root=runs_root)["items"]
    assert set(items) == {"general", "hyp:direct_pattern_hits:D-04", "flag:unanchored_statements:0"}
    # review.json 真落盘
    assert (runs_root / rid / "review.json").is_file()


@pytest.mark.parametrize("bad", ["", "no-colon-prefix", "x" * 200, "a b:c", "../up", "obs:"])
def test_review_rejects_bad_keys(runs_root, bad):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        upsert_review_item("R-20260929T010000Z-bbbbbb", bad, True, None, runs_root=runs_root)
    assert exc.value.status_code == 422


def test_report_image_path_missing(runs_root):
    with pytest.raises(HTTPException) as exc:
        report_image_path("R-20260929T010000Z-bbbbbb", runs_root=runs_root)
    assert exc.value.status_code == 404


def test_get_step_detail_prompt_and_program(runs_root):
    """UI-012：逐步输入/输出——LLM 步给 prompt 原文（缺文件给 missing_hint），程序步给源码。"""
    from app.ui_api import get_step_detail

    run = runs_root / "R-20260929T010000Z-bbbbbb"
    (run / "report.md").write_text("报告初稿", encoding="utf-8")
    (run / "prompts").mkdir()
    (run / "prompts" / "10-generate.md").write_text("生成 prompt 原文", encoding="utf-8")

    d1 = get_step_detail("R-20260929T010000Z-bbbbbb", 1, runs_root=runs_root)
    assert d1["name"] == "报告生成" and d1["ai"] is True
    assert d1["input"]["kind"] == "prompt"
    assert d1["input"]["content"] == "生成 prompt 原文"
    assert d1["input"]["missing_hint"] is None
    assert d1["outputs"][0]["content"] == "报告初稿"

    # 校验步 prompt 未落盘 → missing_hint 明示
    d2 = get_step_detail("R-20260929T010000Z-bbbbbb", 2, runs_root=runs_root)
    assert d2["name"] == "合规与超纲核查" and d2["ai"] is True
    assert d2["input"]["content"] is None
    assert "未落盘" in d2["input"]["missing_hint"]

    d3 = get_step_detail("R-20260929T010000Z-bbbbbb", 3, runs_root=runs_root)
    assert d3["name"] == "渲染交付" and d3["ai"] is False
    assert d3["input"]["kind"] == "program"
    assert "render.py" in d3["input"]["label"]
    assert "render_report_html" in d3["input"]["content"]
    assert d3["outputs"][0]["label"].endswith("report.html")


@pytest.mark.parametrize("bad_step", [0, 4, -1])
def test_get_step_detail_unknown_step(runs_root, bad_step):
    from fastapi import HTTPException
    from app.ui_api import get_step_detail
    with pytest.raises(HTTPException) as exc:
        get_step_detail("R-20260929T010000Z-bbbbbb", bad_step, runs_root=runs_root)
    assert exc.value.status_code == 404


# ---------- UI-013 链路结构元数据下发（/pipeline） ----------

def _write_gen_audit_run(run_dir: Path) -> None:
    """gen-audit-v1 run 最小产物集：run.json（新口径键）+ report.md + audit.md。"""
    run_dir.mkdir(parents=True)
    (run_dir / "report.md").write_text("报告初稿", encoding="utf-8")
    (run_dir / "audit.md").write_text("## 合规核查\n\n**合规通过。**\n", encoding="utf-8")
    meta = {"report_id": run_dir.name, "pipeline": "gen-audit-v1", "status": "completed",
            "started_at": "2026-10-19T00:00:00+00:00", "elapsed_ms": 222056,
            "input": {"theme": "财富", "image_path": str(run_dir / "painting.jpg")},
            "models": {"generate": "k3", "audit": "k3"},
            "timings_ms": {"generate": 65850, "audit": 156206},
            "token_usage": {
                "generate": {"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000},
                "audit": {"prompt_tokens": 4000, "completion_tokens": 1000, "total_tokens": 5000},
                "total": {"prompt_tokens": 5000, "completion_tokens": 3000, "total_tokens": 8000}}}
    (run_dir / "run.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def test_pipeline_gen_audit_steps_match_meta(tmp_path):
    """UI-013：/pipeline 下发的步数/名称与 _STEP_META 一致，耗时/token/产物存在性来自 run.json。"""
    from app.ui_api import _STEP_META, get_pipeline
    _write_gen_audit_run(tmp_path / "r20261019000000")
    p = get_pipeline("r20261019000000", runs_root=tmp_path)
    assert p["legacy"] is False and p["pipeline"] == "gen-audit-v1"
    assert len(p["steps"]) == len(_STEP_META) == 3
    assert [s["name"] for s in p["steps"]] == [m["name"] for m in _STEP_META.values()]
    s1, s2, s3 = p["steps"]
    assert s1["cost_ms"] == 65850 and s1["tokens"]["total"] == 3000 and s1["tool"] == "k3"
    assert s2["cost_ms"] == 156206 and s2["ai"] is True
    assert s3["ai"] is False and s3["cost_ms"] is None and s3["tokens"] is None
    # 产物存在性按 run 目录实况：report.md/audit.md 在，report.html 不在
    assert s1["outputs"][0]["exists"] is True
    assert s2["outputs"][0]["exists"] is True
    assert s3["outputs"][0] == {"file": "report.html", "label": "单文件 HTML（米色鎏金主题）",
                                "exists": False}
    assert p["elapsed_ms"] == 222056 and p["token_total"]["total_tokens"] == 8000


def test_pipeline_legacy_run_degrades(runs_root):
    """旧 stage35 run（无 pipeline 字段）→ legacy 标记 + 降级提示，不返回三步结构。"""
    from app.ui_api import get_pipeline
    p = get_pipeline("R-20260929T010000Z-bbbbbb", runs_root=runs_root)
    assert p["legacy"] is True and p["pipeline"] == "stage35"
    assert p["steps"] == [] and p["note"]


# ---------- D-119 感知记分牌 ----------

def _write_scored_run(run_dir: Path, image_name: str, perception: str) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "perception.md").write_text(perception, encoding="utf-8")
    meta = {"report_id": run_dir.name, "status": "completed",
            "input": {"theme": "测试", "image_path": f"/fake/{image_name}"},
            "models": {}, "g1": None, "token_usage": {}, "timings_ms": {}}
    (run_dir / "run.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def test_perception_score_matches_truth_and_scores(tmp_path, monkeypatch):
    """真值表按图文件名匹配；✓/✗/未提判定与命中率正确。"""
    from app import perception_eval
    truth_dir = tmp_path / "truths"
    truth_dir.mkdir()
    (truth_dir / "imgX.truth.json").write_text(json.dumps({
        "painting": "imgX", "image": "samples/paintings-marked/IMG_X.jpeg",
        "items": [
            {"id": "x-color-ok", "region": "内圈", "item": "中心颜色", "type": "contains",
             "keywords": ["中心"], "expect_any": ["浅黄"], "truth_desc": "浅黄"},
            {"id": "x-color-no", "region": "外圈", "item": "外缘颜色", "type": "contains",
             "keywords": ["外缘"], "expect_any": ["红色"], "truth_desc": "红色"},
        ]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(perception_eval, "TRUTH_DIR", truth_dir)
    run = tmp_path / "runs" / "R-score-001"
    _write_scored_run(run, "IMG_X.jpeg", "**内圈**：中心八瓣花，浅黄色。**外圈**：外缘是绿色。")
    result = perception_eval.score_run(run, "IMG_X.jpeg")
    assert result["truth"] == "imgX.truth.json"
    assert (result["hit"], result["total"]) == (1, 2)   # 浅黄✓ 红✗
    assert result["items"][0]["verdict"] == "✓"
    assert result["items"][1]["verdict"] == "✗"
    miss = tmp_path / "runs" / "R-score-002"
    _write_scored_run(miss, "IMG_X.jpeg", "**整体**：画面描述，未提中心细节。")
    result2 = perception_eval.score_run(miss, "IMG_X.jpeg")
    assert (result2["hit"], result2["total"]) == (0, 2)
    assert result2["items"][0]["verdict"] == "✗"      # 有「中心」行但无浅黄声称
    none_run = tmp_path / "runs" / "R-score-003"
    _write_scored_run(none_run, "IMG_X.jpeg", "**整体**：无关描述。")
    result3 = perception_eval.score_run(none_run, "IMG_X.jpeg")
    assert result3["items"][0]["verdict"] == "未提"   # 关键词行都不在


def test_perception_score_no_truth_returns_none(tmp_path, monkeypatch):
    from app import perception_eval
    monkeypatch.setattr(perception_eval, "TRUTH_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    run = tmp_path / "runs" / "R-score-003"
    _write_scored_run(run, "IMG_NOPE.jpeg", "任何描述")
    assert perception_eval.score_run(run, "IMG_NOPE.jpeg") is None
