"""教学版样本生成（wf-report-teaching v1.0.0 契约的首次出样）。

知识供给：KB 主题知识包（schools/mandala/theme-packs/ 装配清单，确定性装配）。
手册原文不进上下文；KB 未覆盖处在文中标注「体系待补」，作为缺口回补知识库。

两次调用（六章单次调用在 ~10 万字符知识包下连续 504，2026-10-19 拆分的生产形态）：
- 调用 A：第一~四章（手册主体，主题级资产，不带图）
- 调用 B：第五章真案例篇 + 第六章附则（带图 + 解读类知识子集 + report.md 一致性基准）

输出落同一 run 目录：teaching.md / teaching.html / prompts/30-teach-a.md / 30-teach-b.md。

用法（backend 目录下）：
    PYTHONPATH=. .venv/bin/python scripts/teach_sample.py <marked_image> <theme_pack.json> <run_dir>
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from app.config import settings
from app.core.llm import REPO_ROOT
from app.workflows.report_gen.render import render_report_html

RANRAN_ROOT = REPO_ROOT.parent.parent


def _call(prompt: str, image_path: Path | None) -> tuple[str, dict, int]:
    """单次模型调用（OpenAI 兼容 chat/completions），image_path 为 None 时纯文本。"""
    content: list[dict] = [{"type": "text", "text": prompt}]
    if image_path is not None:
        suffix = image_path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        data_url = f"data:{mime};base64," + base64.b64encode(image_path.read_bytes()).decode()
        content.append({"type": "image_url", "image_url": {"url": data_url}})
    body = {"model": settings.kimi_model,
            "messages": [{"role": "user", "content": content}], "temperature": 1}
    t0 = time.perf_counter()
    req = urllib.request.Request(
        settings.kimi_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {settings.kimi_api_key.strip()}",
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=900) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    elapsed = int((time.perf_counter() - t0) * 1000)
    usage = payload.get("usage") or {}
    return payload["choices"][0]["message"]["content"], usage, elapsed


def _extract_section(text: str, heading_prefix: str) -> str:
    """按标题前缀抽取 markdown 一节（到同级或更高级标题为止）。"""
    lines = text.splitlines()
    level = len(heading_prefix) - len(heading_prefix.lstrip("#"))
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading_prefix)), None)
    if start is None:
        return f"（装配警告：未找到小节 {heading_prefix}）"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.startswith("#") and (len(ln) - len(ln.lstrip("#"))) <= level:
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def _read_source(src: dict) -> str:
    p = RANRAN_ROOT / src["path"]
    if not p.is_file():
        return f"（装配警告：文件缺失 {src['path']}）"
    text = p.read_text(encoding="utf-8")
    inc = src["include"]
    if isinstance(inc, dict):
        if "sections" in inc:
            text = "\n\n".join(_extract_section(text, h) for h in inc["sections"])
        elif "section" in inc:
            text = _extract_section(text, inc["section"])
    return f"### 〔{src['role']}〕来源：{src['path']}\n\n{text}"


def load_theme_pack(pack_path: Path) -> tuple[str, str]:
    """装配手册主体知识包（sources），返回 (知识包文本, 主题名)。"""
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(_read_source(s) for s in pack["sources"]), pack["theme"]


def load_case_pack(pack_path: Path) -> str:
    """装配案例篇知识子集（case_sources，解读类文件）。"""
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(_read_source(s) for s in pack["case_sources"])


_VOICE = """语态：资深疗愈师写给新人同行，温和、笃定；称呼读者用「你」或不称呼，**不用「徒弟」这类师徒称谓**；句子要慢，短句为主；不用 emoji，不堆术语与玄学黑话，不写对仗金句。不做医学/心理诊断，不做确定性承诺。"""

_RULES = """知识忠实：所有规则性说法以随附知识包为准；引用时注明来源（文档名或稳定 ID），**不说「手册说」**。知识包没有覆盖、但教学上需要的内容，可以用通识经验补写，但该句必须带标注「（体系待补）」——这些标注是知识库回补的缺口清单。负向解读必给生机与修复路径。"""


def _handbook_prompt(theme: str, knowledge: str) -> str:
    return f"""你是一位资深曼陀罗疗愈师，正在带一位刚入门的新人解读师。随附本疗愈体系的「{theme}」主题知识包。

你的任务：产出「{theme}」主题曼陀罗解读教学材料的第一至四章（教学版共六章，第五、六章另行生成，你不要写）。读者是 AI 素养不高的新人疗愈师：傻瓜省心，能照着学、照着用。

第一行输出标题：# 曼陀罗「{theme}」主题教学版解读材料

固定四章（Markdown）：

## 第一章 主题认知篇
主题是什么、常见来源、在生命各维度的表现、为什么曼陀罗适合做这个主题、解读师做此主题的定位与边界。

## 第二章 主题解读篇
本主题的三圈定位（内/中/外圈各对应什么）；三圈中的主题信号解读（正面与卡点）；颜色信号速查表；五行失衡与本主题的关联；五行生克修复回路；形状信号；综合判断对照表。

## 第三章 主题个案实操篇
个案准备、引领觉察问题清单、主题解读标准句式与示范（"从你的曼陀罗中可以看出……因为……"）、清理方案、订单画方案、检视与信念锚定、主题金句库。

## 第四章 疗愈方案篇
主题周期计划（清理→滋养→显化三段式）、清理画用色速查、观想脚本、陪跑跟进要点。

硬要求：
1. {_RULES}
2. {_VOICE}
3. 只写到第四章为止，直接输出正文，不要寒暄、不要复述本要求。

本疗愈体系主题知识包：
{knowledge}"""


def _case_prompt(theme: str, case_knowledge: str, report: str) -> str:
    return f"""你是一位资深曼陀罗疗愈师，正在带一位刚入门的新人解读师。附件是一幅曼陀罗（画上的圆圈标记线是疗愈师圈定三圈的辅助记号，不是画作内容，不计入五行）。随附本疗愈体系的解读类知识（子集），以及这幅画的来访者版解读报告。来访者主题：「{theme}」。

你的任务：产出教学版材料的第五章与第六章（第一至四章已另行生成，你不要写）。

## 第五章 真案例篇（本幅画，重点章）
用附件这幅画走完整个案逻辑链：
1. 图面特征：由内向外逐圈描述关键画面事实（三圈归属以标记线为准）；
2. 逐条推理：每条按「画面信号 → 体系依据 → 结论」展开，引用体系规则时注明来源（文档名或稳定 ID，如 议题解读.md 乾宫 / S-001 / IM-xx）；
3. 与来访者版报告的对照讲解：报告每个核心结论对应的推理链，新人容易看不懂或容易质疑的地方重点讲；
4. 根源挖掘引导：个案中如何顺着解读往根源问；
5. 本案清理/滋养/显化方案。
只用这一幅画，不虚构案主背景与身份。

## 第六章 附则
伦理边界与转介指引、解读师自查清单、主题延伸。

硬要求：
1. 一致性：第五章的每个结论必须与来访者版报告一致，不矛盾、不另起炉灶；报告里没下的结论，案例篇不得新增。
2. {_RULES}
3. {_VOICE}
4. 直接输出正文（从 ## 第五章 开始），不要寒暄、不要复述本要求。

解读类知识（子集）：
{case_knowledge}

---

来访者版解读报告（一致性基准）：
{report}"""


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit("用法: teach_sample.py <marked_image> <theme_pack.json> <run_dir>")
    image_path = Path(sys.argv[1])
    pack_path = Path(sys.argv[2])
    run_dir = Path(sys.argv[3])
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    knowledge, theme = load_theme_pack(pack_path)
    case_knowledge = load_case_pack(pack_path)

    prompt_a = _handbook_prompt(theme, knowledge)
    part_a, usage_a, ms_a = _call(prompt_a, None)
    print(f"[teach-a] 手册主体 {ms_a}ms usage={usage_a}", file=sys.stderr)

    prompt_b = _case_prompt(theme, case_knowledge, report)
    part_b, usage_b, ms_b = _call(prompt_b, image_path)
    print(f"[teach-b] 案例篇 {ms_b}ms usage={usage_b}", file=sys.stderr)

    teaching = part_a.rstrip() + "\n\n---\n\n" + part_b.strip() + "\n"
    prompts_dir = run_dir / "prompts"
    (prompts_dir / "30-teach-a.md").write_text(prompt_a, encoding="utf-8")
    (prompts_dir / "30-teach-b.md").write_text(prompt_b, encoding="utf-8")
    write_teaching_outputs(teaching, image_path, run_dir)
    print(f"[teach] {run_dir} 教学版(KB包, 两次调用) 完成", file=sys.stderr)


_SRC_CITATION = re.compile(r"（[^）]*来源：[^）]*）")
_SRC_CSS = ".src{font-size:12px;color:#b3a88f;}"


def render_teaching_html(md_text: str, image_path: Path) -> str:
    """教学版 HTML：复用报告渲染，知识来源标注（…来源：…）弱化显示（小字浅色）。"""
    html_text = render_report_html(md_text, image_path=image_path)
    html_text = _SRC_CITATION.sub(r'<span class="src">\g<0></span>', html_text)
    return html_text.replace("</style>", _SRC_CSS + "\n</style>", 1)


def write_teaching_outputs(teaching: str, image_path: Path, run_dir: Path) -> None:
    """teaching.md / teaching.html 落盘（重渲染现有 md 时单独复用）。"""
    (run_dir / "teaching.md").write_text(teaching, encoding="utf-8")
    (run_dir / "teaching.html").write_text(
        render_teaching_html(teaching, image_path), encoding="utf-8")


if __name__ == "__main__":
    main()
