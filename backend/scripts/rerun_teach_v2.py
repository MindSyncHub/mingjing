"""案例篇 v2 批量重跑（2026-10-20）：case_sources 第一类缺口补装后。

case_sources 从 5 篇扩到 11 篇（补：状态疗愈映射/能量三方向/个案四步骤/
转介红线/自助画法/观察引导问题库），g01+g03~g10 重跑调用 B（案例篇），
g02 复用已验证的 teaching-b-v2.md。手册主体（调用 A 成品）不动。

每张：v1 备份为 teaching-v1.md/html → 新案例篇存 teaching-b-v2.md +
prompts/30-teach-b-v2.md → 拼装新 teaching.md/html → run.json 记
teaching_rerun。断点续跑（进度 JSON），504/502/503 退避重试。

用法（backend 目录下）：
    PYTHONPATH=. .venv/bin/python scripts/rerun_teach_v2.py
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

GOLDEN_DIR = Path("../eval/golden-set/images")
PACK_PATH = Path("../schools/mandala/theme-packs/T-08-财富.json")
G01_TEACHING = Path("../runs/r20261018181150/teaching.md")
RUNS_ROOT = Path("../runs")
THEME = "财富"
CASES = {
    "g01": "r20261018181150",
    "g02": "r20261019110953",
    "g03": "r20261019112533",
    "g04": "r20261019113231",
    "g05": "r20261019114642",
    "g06": "r20261019120754",
    "g07": "r20261019121544",
    "g08": "r20261019124211",
    "g09": "r20261019133812",
    "g10": "r20261019135302",
}
MAX_RETRY = 6
PROGRESS_PATH = RUNS_ROOT / "batch-teach-v2-2026-10-20.json"


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


def _handbook_body() -> str:
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

    for cid, run_name in CASES.items():
        if cases.get(cid, {}).get("done"):
            print(f"[{cid}] 已完成，跳过", file=sys.stderr, flush=True)
            continue
        run_dir = RUNS_ROOT / run_name
        marked = GOLDEN_DIR / f"{cid}-marked.jpeg"

        v2_path = run_dir / "teaching-b-v2.md"
        if v2_path.is_file():
            part_b = v2_path.read_text(encoding="utf-8")
            print(f"[{cid}] 复用已有 teaching-b-v2.md", file=sys.stderr, flush=True)
        else:
            report = (run_dir / "report.md").read_text(encoding="utf-8")
            prompt = _case_prompt(THEME, case_knowledge, report)
            part_b, usage, ms = _with_retry(
                lambda: _call(prompt, marked), f"{cid}/teach-b-v2")
            print(f"[{cid}] 案例篇v2 {ms}ms usage={usage}", file=sys.stderr, flush=True)
            (run_dir / "prompts" / "30-teach-b-v2.md").write_text(prompt, encoding="utf-8")
            v2_path.write_text(part_b, encoding="utf-8")

        # v1 备份（首次才改名）
        for name in ("teaching.md", "teaching.html"):
            src, dst = run_dir / name, run_dir / name.replace("teaching", "teaching-v1")
            if src.is_file() and not dst.is_file():
                src.rename(dst)

        teaching = part_a + "\n\n---\n\n" + part_b.strip() + "\n"
        write_teaching_outputs(teaching, marked, run_dir)

        run_json_path = run_dir / "run.json"
        run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
        run_json["teaching_rerun"] = ("2026-10-20 case_sources 第一类缺口补装"
                                      "（5→11 篇）后重跑案例篇；v1 备份为"
                                      " teaching-v1.md/html；手册主体未变")
        run_json_path.write_text(
            json.dumps(run_json, ensure_ascii=False, indent=2), encoding="utf-8")

        n = teaching.count("体系待补")
        cases[cid] = {"run_dir": run_name, "done": True, "daibu": n}
        save()
        print(f"[{cid}] 完成（体系待补 {n} 处）→ {run_dir}", file=sys.stderr, flush=True)
        time.sleep(15)

    total = sum(e.get("daibu", 0) for e in cases.values())
    print(f"[batch-v2] 全部完成，体系待补合计 {total} 处"
          f"（v1 为 126 处），索引 {PROGRESS_PATH}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
