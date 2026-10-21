"""感知层黄金集记分牌：描述文本 × 真值表自动对分（辅助判分，最终人审）。

用法：
  .venv/bin/python scripts/perception_score.py <desc.md> [desc2.md ...]
      对单个/多个描述文件打分，输出 Markdown 记分牌到
      eval-results/perception-matrix/scoreboard_<stamp>.md（并覆盖 scoreboard.md）。

设计要点（为什么不用通用关键词匹配）：
  自由文本里"8个绿三角+8个蓝三角"是 16 的声称而不是 8——逐行抓数字会误判。
  故数值条目用按条目注册的"声称抽取器"（extractor）抽出模型的主声称数字，
  再与真值比对；抽取器按 item id 注册，新画作的新条目要配新抽取器（见 EXTRACTORS）。
  contains 类条目才用关键词行匹配。核对轮产物自动截取 ## 修订版描述 段。
  凡抽取器返回 None 一律标"未提"，不猜。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
TRUTH_DIR = REPO_ROOT / "eval/golden-perception"
OUT_DIR = REPO_ROOT / "eval-results/perception-matrix"


# ---------- 声称抽取器：返回模型对该条目的主声称数字，None = 未提 ----------

def _ex_inner_rays(text: str) -> int | None:
    for pat in (r"(\d+)\s*条[^\n。；]*(?:放射|辐射)",
                r"(?:放射|辐射)[^\n。；]*?(\d+)\s*条"):
        m = re.search(pat, text)
        if m:
            return int(m.group(1))
    return None


def _ex_mid_triangles(text: str) -> int | None:
    m = re.search(r"共\s*(\d+)\s*个[^，。\n]*大三角", text)
    if m:
        return int(m.group(1))
    g = re.search(
        r"(\d+)\s*个绿[^，。\n]*三角[^，。\n]*?(\d+)\s*个蓝[^，。\n]*三角"
        r"|(\d+)\s*个蓝[^，。\n]*三角[^，。\n]*?(\d+)\s*个绿[^，。\n]*三角", text)
    if g:
        return sum(int(x) for x in g.groups() if x)
    m = re.search(r"(\d+)\s*个[^(（，。\n]*大三角", text)
    return int(m.group(1)) if m else None


def _ex_moon_groups(text: str) -> int | None:
    for ln in text.splitlines():
        if ("满月" in ln or "新月" in ln or "月相" in ln or "日月" in ln) and "月" in ln:
            m = re.search(r"(\d+)\s*组", ln)
            if m:
                return int(m.group(1))
    return None


def _ex_stars_total(text: str) -> int | None:
    m = re.search(r"共\s*(\d+)\s*颗", text)  # 描述自带汇总，直接用
    if m:
        return int(m.group(1))
    claims: list[int] = []
    for m in re.finditer(r"(\d+)\s*(?:[–—~-]\s*(\d+))?\s*颗", text):
        claims.append(max(int(m.group(1)), int(m.group(2) or 0)))
    if claims:
        return sum(claims)
    for ln in text.splitlines():
        if "星" in ln:
            m = re.search(r"共\s*(\d+)\s*组", ln)
            if m:
                return int(m.group(1)) * 2  # 每组粉+紫各一
    return None


def _ex_v_chevrons(text: str) -> int | None:
    for ln in text.splitlines():
        if any(k in ln for k in ("V形", "箭头", "叶纹", "叶片")):
            m = re.search(r"约?\s*(\d+)\s*(?:组|个重复单元|个单元)", ln)
            if m:
                return int(m.group(1))
    return None


def _ex_diamonds(text: str) -> int | None:
    for ln in text.splitlines():
        if "菱形" in ln:
            m = re.search(r"约?\s*(\d+)\s*(?:处|个)", ln)
            if m:
                return int(m.group(1))
    return None


def _ex_p79_center_petal_colors(text: str) -> int | None:
    """花心花瓣声称了几种颜色。
    强证据：同一分句内「交替」+黄+绿+瓣（复核段典型句式，直接判 2）；
    弱证据：中心/圆心后 18 字窗口内的颜色声称（窗口截断防长句串味）。"""
    for ln in text.splitlines():
        for c in re.split(r"[。；、]", ln):  # 顿号也切：防枚举长句串味
            if "交替" in c and "瓣" in c and "黄" in c and "绿" in c:
                return 2
    yellow = green = False
    for m in re.finditer(r"(?:中心|花心|圆心)([^，。；\n]{0,18})", text):
        seg = m.group(1)
        if "瓣" not in seg and "花" not in seg:
            continue
        if "黄" in seg:
            yellow = True
        if "绿" in seg:
            green = True
    if not (yellow or green):
        return None
    return int(yellow) + int(green)


def _ex_p79_center_petal_count(text: str) -> int | None:
    """花心花瓣数：分句级匹配（中心/最内层/圆心 + 瓣），防长句尾部数字串味。"""
    for ln in text.splitlines():
        for c in re.split(r"[。；]", ln):
            if ("中心" in c or "最内层" in c or "圆心" in c) and "瓣" in c:
                m = re.search(r"(\d+)\s*个[^，。；]{0,6}?瓣", c) or re.search(r"(\d+)\s*瓣", c)
                if m:
                    return int(m.group(1))
                if "八瓣" in c:
                    return 8
    return None


def _ex_p79_orange_tips(text: str) -> int | None:
    for ln in text.splitlines():
        if "橙" in ln and ("尖角" in ln or "三角" in ln):
            m = re.search(r"(\d+)\s*个", ln)
            if m:
                return int(m.group(1))
            if "八个" in ln:
                return 8
    return None


def _ex_p79_blue_rects(text: str) -> int | None:
    for ln in text.splitlines():
        if "深蓝" in ln and ("矩形" in ln or "长条" in ln or "长块" in ln):
            m = re.search(r"(\d+)\s*根", ln)
            if m:
                return int(m.group(1))
    return None


def _ex_p79_pink_stars(text: str) -> int | None:
    for ln in text.splitlines():
        if ("粉" in ln or "品红" in ln) and "星" in ln:
            m = re.search(r"共\s*(\d+)\s*(?:个|颗)", ln)
            if m:
                return int(m.group(1))
    return None


EXTRACTORS = {
    "inner-rays": _ex_inner_rays,
    "mid-triangles": _ex_mid_triangles,
    "moon-groups": _ex_moon_groups,
    "stars-total": _ex_stars_total,
    "v-chevrons": _ex_v_chevrons,
    "diamonds": _ex_diamonds,
    "p79-center-petal-colors": _ex_p79_center_petal_colors,
    "p79-center-petal-count": _ex_p79_center_petal_count,
    "p79-orange-tips": _ex_p79_orange_tips,
    "p79-blue-rects": _ex_p79_blue_rects,
    "p79-pink-stars": _ex_p79_pink_stars,
}


# ---------- 计分 ----------

def _extract_revised(text: str) -> str:
    """核对轮产物：取 ## 修订版描述 段；写"无需修订"则取原描述。"""
    marker = "## 修订版描述"
    if marker not in text:
        return text
    head, tail = text.split(marker, 1)
    return head if "无需修订" in tail[:200] else tail


def score_item(item: dict, text: str) -> tuple[str, str]:
    iid, it = item["id"], item["type"]
    if iid in EXTRACTORS:
        claim = EXTRACTORS[iid](text)
        if claim is None:
            return "未提", ""
        if it == "count":
            ok = claim == item["expect"]
        else:
            ok = item["lo"] <= claim <= item["hi"]
        return ("✓" if ok else "✗"), f"声称 {claim}"
    if it == "contains":
        kws = item["keywords"]
        if item.get("match") == "any":
            lines = [ln for ln in text.splitlines() if any(k in ln for k in kws)]
        else:
            lines = [ln for ln in text.splitlines() if all(k in ln for k in kws)]
        if not lines:
            return "未提", ""
        joined = " ".join(lines)
        if any(w in joined for w in item.get("expect_any", [])):
            return "✓", ""
        if item.get("forbid") and all(w in joined for w in item["forbid"]):
            return "✗", "命中禁用词"
        return "✗", "未命中期望词"
    return "?", f"未知条目类型 {it}"


def score_file(truth: dict, path: Path) -> dict[str, tuple[str, str]]:
    text = _extract_revised(path.read_text(encoding="utf-8"))
    return {item["id"]: score_item(item, text) for item in truth["items"]}


def main(argv: list[str]) -> int:
    truth_name = "img5067.truth.json"
    argv = list(argv)
    if argv and argv[0].startswith("--truth="):
        truth_name = argv.pop(0).split("=", 1)[1]
    if not argv:
        print("用法: perception_score.py [--truth=<真值表>] <desc.md> [desc2.md ...]", file=sys.stderr)
        return 2
    truth_path = TRUTH_DIR / truth_name
    truth = json.loads(truth_path.read_text(encoding="utf-8"))

    cols: list[tuple[str, dict[str, tuple[str, str]]]] = []
    for arg in argv:
        p = Path(arg)
        cols.append((p.stem, score_file(truth, p)))

    n = len(truth["items"])
    lines = [f"# 感知记分牌（{truth['painting']}）",
             f"生成：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}Z · 真值表：{truth_path.name}\n",
             "| 区域 | 条目 | 真值 | " + " | ".join(name for name, _ in cols) + " |",
             "|" + "---|" * (3 + len(cols))]
    for item in truth["items"]:
        cells = []
        for _, scores in cols:
            mark, note = scores[item["id"]]
            cells.append(mark if not note else f"{mark} {note}")
        lines.append(f"| {item['region']} | {item['item']} | {item['truth_desc']} | "
                     + " | ".join(cells) + " |")
    lines.append("")
    lines.append("| **命中率** |  |  | " + " | ".join(
        f"**{sum(1 for s in scores.values() if s[0] == '✓')}/{n}**"
        for _, scores in cols) + " |")
    lines.append("")
    lines.append("图例：✓ 命中 · ✗ 未命中（附模型主声称值）· 未提 描述中找不到对应声称。"
                 "本表为自动辅助判分，命中率仅作排序参考，最终以人工审定为准。")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = "\n".join(lines) + "\n"
    (OUT_DIR / f"scoreboard_{stamp}.md").write_text(report, encoding="utf-8")
    (OUT_DIR / "scoreboard.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
