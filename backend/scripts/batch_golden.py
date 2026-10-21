"""黄金集批量回归（task 013）：g02–g10 逐张跑完整链。

每张图：生成臂 + 审计臂（gen-audit-v1）→ 教学版调用 B（案例篇+附则，
手册主体复用 g01 的调用 A 产出，主题级资产不重跑）。
504/502/503 退避重试（2026-10-19 网关波动教训）。

用法（backend 目录下）：
    PYTHONPATH=. .venv/bin/python scripts/batch_golden.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from teach_sample import (_call, _case_prompt, load_case_pack,  # noqa: E402
                          write_teaching_outputs)

from app.workflows.report_gen import GenAuditError, run_gen_audit  # noqa: E402

GOLDEN_DIR = Path("../eval/golden-set/images")
PACK_PATH = Path("../schools/mandala/theme-packs/T-08-财富.json")
G01_TEACHING = Path("../runs/r20261018181150/teaching.md")
RUNS_ROOT = Path("../runs")
THEME = "财富"
CASE_IDS = [f"g{i:02d}" for i in range(2, 11)]

MAX_RETRY = 6
PROGRESS_PATH = RUNS_ROOT / "batch-golden-2026-10-19.json"


def _with_retry(fn, label: str):
    """网关 5xx 退避重试（HTTPError 与 gen_audit 包装后的 GenAuditError 都认）；其他错误直接抛。"""
    for attempt in range(1, MAX_RETRY + 2):
        try:
            return fn()
        except (urllib.error.HTTPError, GenAuditError) as exc:
            code = getattr(exc, "code", None)
            retryable = code in (502, 503, 504) or any(
                s in str(exc) for s in ("502", "503", "504"))
            if retryable and attempt <= MAX_RETRY:
                wait = min(60 * attempt, 300)
                print(f"[{label}] 网关错误，{wait}s 后第 {attempt} 次重试",
                      file=sys.stderr, flush=True)
                time.sleep(wait)
            else:
                raise


def _handbook_body() -> str:
    """g01 教学版的前四章（手册主体），截到第五章之前。"""
    text = G01_TEACHING.read_text(encoding="utf-8")
    head = text.split("\n## 第五章", 1)[0]
    return head.rstrip().rstrip("-").rstrip()


def main() -> None:
    part_a = _handbook_body()
    case_knowledge = load_case_pack(PACK_PATH)
    progress = {"theme": THEME, "cases": {}}
    if PROGRESS_PATH.is_file():
        progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    cases = progress.setdefault("cases", {})

    def save():
        PROGRESS_PATH.write_text(json.dumps(progress, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

    for cid in CASE_IDS:
        entry = cases.get(cid, {})
        if entry.get("done"):
            print(f"[{cid}] 已完成，跳过", file=sys.stderr, flush=True)
            continue
        marked = GOLDEN_DIR / f"{cid}-marked.jpeg"
        original = GOLDEN_DIR / f"{cid}.jpeg"
        if not marked.is_file():
            print(f"[{cid}] 缺标记图，跳过: {marked}", file=sys.stderr, flush=True)
            continue
        if entry.get("run_dir"):
            run_dir = RUNS_ROOT / entry["run_dir"]
            print(f"[{cid}] 断点续跑：复用 {run_dir.name}，只补案例篇", file=sys.stderr,
                  flush=True)
        else:
            run_dir = _with_retry(
                lambda: run_gen_audit(marked, theme=THEME, runs_root=RUNS_ROOT,
                                      original_path=original), f"{cid}/gen-audit")
            cases[cid] = {"run_dir": run_dir.name, "done": False}
            save()
        report = (run_dir / "report.md").read_text(encoding="utf-8")

        prompt_b = _case_prompt(THEME, case_knowledge, report)
        part_b, usage_b, ms_b = _with_retry(
            lambda: _call(prompt_b, marked), f"{cid}/teach-b")
        print(f"[{cid}] 案例篇 {ms_b}ms usage={usage_b}", file=sys.stderr, flush=True)

        teaching = part_a + "\n\n---\n\n" + part_b.strip() + "\n"
        (run_dir / "prompts" / "30-teach-b.md").write_text(prompt_b, encoding="utf-8")
        write_teaching_outputs(teaching, marked, run_dir)
        cases[cid]["done"] = True
        save()
        print(f"[{cid}] 完成 → {run_dir}", file=sys.stderr, flush=True)
        time.sleep(15)

    done = sum(1 for e in cases.values() if e.get("done"))
    print(f"[batch] 全部完成 {done}/{len(CASE_IDS)}，索引 {PROGRESS_PATH}",
          file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
