"""D-01 尺子修正后重跑审计臂（2026-10-20）。

背景：直断法库 D-01 误加手册没有的「最外缘织边连续」限制（已修正，
见 knowledge/healing/术/流派/曼陀罗/直断解读.md）。g01/g03/g05/g07/g08
五张的审计疑点由错误尺子造成，生成臂报告不动，只重跑审计臂：
重写 audit.md 与 prompts/20-audit.md，更新 run.json 的 audit 用量。

用法（backend 目录下）：
    PYTHONPATH=. .venv/bin/python scripts/rerun_audit_d01.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.workflows.report_gen.gen_audit import (  # noqa: E402
    MANUAL_PATH, RULER_PATH, _audit_prompt, _vl_call)

GOLDEN_DIR = Path("../eval/golden-set/images")
RUNS_ROOT = Path("../runs")
THEME = "财富"
CASES = {
    "g01": "r20261018181150",
    "g03": "r20261019112533",
    "g05": "r20261019114642",
    "g07": "r20261019121544",
    "g08": "r20261019124211",
}
MAX_RETRY = 6


def _with_retry(fn, label: str):
    for attempt in range(1, MAX_RETRY + 2):
        try:
            return fn()
        except urllib.error.HTTPError as exc:
            if exc.code in (502, 503, 504) and attempt <= MAX_RETRY:
                wait = min(60 * attempt, 300)
                print(f"[{label}] 网关 {exc.code}，{wait}s 后第 {attempt} 次重试",
                      file=sys.stderr, flush=True)
                time.sleep(wait)
            else:
                raise


def main() -> None:
    manual = MANUAL_PATH.read_text(encoding="utf-8")
    ruler = RULER_PATH.read_text(encoding="utf-8")
    for cid, run_name in CASES.items():
        run_dir = RUNS_ROOT / run_name
        image = GOLDEN_DIR / f"{cid}-marked.jpeg"
        draft = (run_dir / "report.md").read_text(encoding="utf-8")
        prompt = _audit_prompt(THEME, manual, ruler, draft)

        audit, usage, ms = _with_retry(
            lambda: _vl_call(prompt, image), f"{cid}/audit")
        print(f"[{cid}] 审计重跑 {ms}ms usage={usage}", file=sys.stderr, flush=True)

        (run_dir / "prompts" / "20-audit.md").write_text(prompt, encoding="utf-8")
        (run_dir / "audit.md").write_text(audit.rstrip() + "\n", encoding="utf-8")

        run_json_path = run_dir / "run.json"
        run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
        run_json.setdefault("token_usage", {})["audit"] = usage
        run_json.setdefault("timings_ms", {})["audit"] = ms
        run_json["audit_rerun"] = ("2026-10-20 D-01 尺子修正（删除手册没有的"
                                   "「最外缘织边连续」限制）后重跑审计臂；"
                                   "report.md 未变")
        run_json_path.write_text(
            json.dumps(run_json, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{cid}] 完成 → {run_dir}", file=sys.stderr, flush=True)
        time.sleep(15)

    print("[rerun] 5 张审计臂全部重跑完成", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
