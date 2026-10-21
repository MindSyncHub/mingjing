"""报告重渲染 CLI（D-110）：report.md（含疗愈师手工编辑后的版本）→ report.html。

用法（从 backend 目录运行）：
    python scripts/render_report.py --md runs/R-xxx/report.md
    python scripts/render_report.py --md runs/R-xxx/report.md --out runs/R-xxx/report.html

口径（D-109）：产物为单文件 HTML，浏览器打开 → 打印 → 存为 PDF 即完成交付。
渲染耗时打印到 stdout，对应验收 PERF-005 / M-005（< 10 秒）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.workflows.report_gen.render import render_report_html  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="report.md → 单文件 HTML 重渲染（确定性，不经 LLM）")
    ap.add_argument("--md", required=True, help="report.md 路径（干净版）")
    ap.add_argument("--out", default=None, help="输出路径，默认与 md 同目录 report.html")
    ap.add_argument("--image", default=None, help="曼陀罗画作路径，给定时内嵌进 hero 区（base64）")
    args = ap.parse_args()
    md_path = Path(args.md)
    if not md_path.exists():
        print(f"文件不存在: {md_path}", file=sys.stderr)
        return 1
    out_path = Path(args.out) if args.out else md_path.with_name("report.html")
    started = time.perf_counter()
    html = render_report_html(md_path.read_text(encoding="utf-8"), image_path=args.image)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if out_path.exists() and out_path.read_text(encoding="utf-8") == html:
        print(f"无变化，跳过写入: {out_path}（{elapsed_ms}ms）")
        return 0
    out_path.write_text(html, encoding="utf-8")
    print(f"已渲染: {out_path}（{elapsed_ms}ms，{len(html)} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
