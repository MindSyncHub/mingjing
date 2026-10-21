"""用 G 臂同款校验 prompt 审计外部报告（C/D/E/F），横向比"每份报告藏几条幻觉"。
用法（backend 目录，需 dashscope 环境变量）：
    python scripts/audit_external_reports.py --cases 001,002
"""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
import os
os.chdir(BACKEND_DIR)

from scripts.blind_cases_runner import MANUAL, OUT_ROOT, _vl_call  # noqa: E402

AUDIT_TMPL = """你是一名严格的曼陀罗解读评审。附件是一幅曼陀罗（三圈已由疗愈师用标记线圈定，标记线不是画作内容）、《曼陀罗解读手册》原文，以及另一位疗愈师对这幅画写的解读报告初稿。

你的任务：不重新解读，只审计这份报告。

1. 提取报告中的核心论断（识别类：颜色/圈层/形状/相邻关系；解读类：直断、五行生克、主题结论），逐条核查：
   - 画面证据：报告声称的画面特征在原图中是否真实存在（✓ / ✗ / 部分）
   - 手册依据：该论断引用的规则在手册中是否存在、是否被正确套用（✓ / ✗ / 曲解）
   - 判定：成立 / 存疑 / 幻觉；存疑或幻觉时给出修正

硬规则：
A. 引用手册时必须抄写手册原文句子作为依据，禁止编造页码、章节号或不存在的条目。
B. 涉及颜色裁决时，先写出你自己看到的颜色，并标注你对此颜色判断的置信度（高/中/低）；
   置信度为"低"的颜色分歧不得作为判定对方"幻觉"的依据，只能标"存疑"并说明两种可能。
C. 你自己的画面判断同样可能出错——拿不准时宁可标"存疑"，不要把猜测写成定论。
2. 幻觉清单：报告中没有画面或手册依据的说法（无中生有的颜色、形状、规则）。
3. 遗漏清单：按手册规则，画面里明显存在、但报告漏掉的重要信号（该触发的直断没触发等）。

输出格式（Markdown）：
## 逐条核查表
| # | 报告论断 | 画面证据 | 手册依据 | 判定 | 修正 |
|---|---|---|---|---|---|
## 幻觉清单
## 遗漏清单
## 总评
（100 字内：这份报告可信吗，主要问题是什么）

《曼陀罗解读手册》原文：
{manual}

---

待审计的解读报告初稿：
{draft}"""

# 案例图（疗愈师三圈标记原图）
ASSETS = Path(os.environ.get("MINGJING_KB_ASSETS", "knowledge/healing/cases/assets"))

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    args = ap.parse_args()
    manual = MANUAL.read_text(encoding="utf-8")
    for cid in args.cases.split(","):
        cid = cid.strip()
        rounds = OUT_ROOT / f"case-{cid}" / "rounds"
        img = None
        for ext in ("jpg", "png"):
            p = ASSETS / f"case-{cid}-mandala-3q.{ext}"
            if p.exists():
                img = p; break
        assert img, f"case-{cid} 缺图"
        for report in sorted(rounds.glob("*.md")):
            name = report.stem
            if name.startswith(("A-", "B-", "G-")) or name.endswith("-audit"):
                continue
            out = rounds / f"{name}-audit.md"
            if out.exists() and out.stat().st_size > 0:
                print(f"[skip] {out.name} 已存在")
                continue
            draft = report.read_text(encoding="utf-8")
            if not draft.strip():
                print(f"[skip] {report.name} 空文件")
                continue
            t0 = time.perf_counter()
            audit, usage, ms = _vl_call(AUDIT_TMPL.format(manual=manual, draft=draft), img)
            out.write_text(audit, encoding="utf-8")
            print(f"[ok] case-{cid} {name} 审计 {ms}ms usage={usage}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
