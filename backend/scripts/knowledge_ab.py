"""知识源三臂对比实验（2026-10-13 MindSyncHub拍板）：生成臂喂不同知识，校验臂固定对照。

臂 M（基线）：gen=删案例版手册——直接用今日 blind-2026-10-cases 的 r4/r5，不重跑。
臂 O（本体论）：gen=knowledge/healing/术/流派/曼陀罗/ 12 份拼接。
臂 C（含案例）：gen=含 11 案例版手册。
三臂校验臂均为：删案例版手册 + 直断法库尺子（单一变量=生成臂知识源）。

用法（在 backend 目录下，先 export 视觉通道三件套）：
    python3 scripts/knowledge_ab.py O case-001
    python3 scripts/knowledge_ab.py C case-002
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.workflows.report_gen import gen_audit as ga  # noqa: E402

RANRAN = ga.RANRAN_ROOT
OUT_ROOT = ga.REPO_ROOT / "eval-results" / "knowledge-ab-2026-10-13"

CASES = {
    "case-001": {"image": RANRAN / "knowledge/healing/cases/assets/case-001-mandala-3q.jpg",
                 "theme": "我是值得的，我是配得的"},
    "case-002": {"image": RANRAN / "knowledge/healing/cases/assets/case-002-mandala-3q.jpg",
                 "theme": "个人成长和财富"},
}

MANUAL_NO_CASE = RANRAN / "products/aimandala/docs/疗愈体系知识库/20-疗愈体系/20-流派层/10-曼陀罗/90-来源原文/曼陀罗解读手册原文.md"
MANUAL_WITH_CASE = RANRAN / "products/aimandala/docs/疗愈体系知识库/20-疗愈体系/20-流派层/10-曼陀罗/90-来源原文/01-曼陀罗解读手册原文.md"
ONTO_DIR = RANRAN / "knowledge/healing/术/流派/曼陀罗"
ONTO_ORDER = ["流派卡", "圆圈图谱", "五行解读", "视觉信号映射", "直断解读", "组合模式",
              "状态五行映射", "议题解读", "解读链路", "解读用法", "观察引导问题库", "自助画法"]


def ontology_concat() -> str:
    parts = []
    for name in ONTO_ORDER:
        p = ONTO_DIR / f"{name}.md"
        parts.append(f"# 【本体论文档：{name}】\n\n{p.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(parts)


def gen_prompt_with_label(theme: str, knowledge: str, label: str) -> str:
    base = ga._gen_prompt(theme, "")
    return base.replace("《曼陀罗解读手册》原文：\n", f"{label}：\n") + knowledge


def main() -> None:
    arm, case = sys.argv[1], sys.argv[2]
    c = CASES[case]
    control_manual = MANUAL_NO_CASE.read_text(encoding="utf-8")
    ruler = ga.RULER_PATH.read_text(encoding="utf-8")
    if arm == "O":
        knowledge = ontology_concat()
        prompt = gen_prompt_with_label(c["theme"], knowledge, "《曼陀罗解读方法体系知识库》（本体论结构化版）")
    elif arm == "C":
        prompt = ga._gen_prompt(c["theme"], MANUAL_WITH_CASE.read_text(encoding="utf-8"))
    else:
        raise SystemExit("arm 只能是 O 或 C（M 基线用今日已有 runs）")

    t0 = time.perf_counter()
    draft, gen_usage, gen_ms = ga._vl_call(prompt, c["image"])
    audit, audit_usage, audit_ms = ga._vl_call(
        ga._audit_prompt(c["theme"], control_manual, ruler, draft), c["image"])
    rid = "r" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rd = OUT_ROOT / arm / case / "runs" / rid
    (rd / "prompts").mkdir(parents=True)
    (rd / "prompts" / "10-generate.md").write_text(prompt, encoding="utf-8")
    (rd / "prompts" / "20-audit.md").write_text(
        ga._audit_prompt(c["theme"], control_manual, ruler, draft), encoding="utf-8")
    (rd / "report.md").write_text(draft.rstrip() + "\n", encoding="utf-8")
    # 口径（2026-10-13 MindSyncHub定）：解读报告默认出单文件 HTML，页面内嵌画作
    from app.workflows.report_gen.render import render_report_html
    (rd / "report.html").write_text(
        render_report_html(draft.rstrip() + "\n", image_path=c["image"]), encoding="utf-8")
    (rd / "audit.md").write_text(audit.rstrip() + "\n", encoding="utf-8")
    (rd / "run.json").write_text(json.dumps({
        "report_id": rid, "pipeline": f"gen-audit-v1-knowledgeAB-arm{arm}", "status": "completed",
        "input": {"image_path": str(c["image"]), "theme": c["theme"]},
        "knowledge": {"gen_arm": arm,
                      "gen_source": "ontology-12docs" if arm == "O" else str(MANUAL_WITH_CASE),
                      "audit_source": str(MANUAL_NO_CASE), "ruler": str(ga.RULER_PATH)},
        "models": {"generate": ga.settings.kimi_model, "audit": ga.settings.kimi_model},
        "token_usage": {"generate": gen_usage, "audit": audit_usage},
        "timings_ms": {"generate": gen_ms, "audit": audit_ms},
        "elapsed_ms": int((time.perf_counter() - t0) * 1000)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[knowledge-AB] {rd} 生成{gen_ms}ms+校验{audit_ms}ms", file=sys.stderr)


if __name__ == "__main__":
    main()
