"""报告渲染步（D-110）：report.md（干净版）→ 单文件 HTML（来访者交付版）。

确定性渲染：纯规则映射，不经 LLM（与 D-097「程序杀确定性错误」同构；
示范的 verdict/chain/feel 等富组件是示范写作层的实例，机械映射是伪结构）。
视觉主题复用黄金示范（docs/golden-report-exemplar-v1.html 的米色/鎏金配色
与衬线标题体系），无外部依赖（不引字体/不引 CDN，单文件可微信转发、离线打开）。
PDF 交付口径（D-109）：浏览器打开本文件 → 打印 → 存为 PDF。

结构映射（写死）：
- 首行「曼陀罗解读报告」+「解读主题：X」→ hero 头
- 首个 ## 之前的段落（定调段）→ lead 框
- ## X → 章节（鎏金章节号 01/02… 装饰）；### X → 小节
- 标准免责声明段（含「不是诊断」且「AI 是辅助工具」）→ 免责块
- ## 待疗愈师核对 起全部不进入来访者版（疗愈师工作材料，边界与 G1 正文切分一致）
- - 列表项 → ◆ 饰列表；> 引用 → 注记；**加粗** → 金强调
"""
from __future__ import annotations

import base64
import html
import mimetypes
import re
from pathlib import Path

DISCLAIMER_MARKERS = ("不是诊断", "AI 是辅助工具")
APPENDIX_HEADING = "## 待疗愈师核对"

_CSS = """:root{--cream:#f7f0e2;--paper:#fffdf7;--ink:#3a362e;--sub:#756b5c;--gold:#c08f2e;--gold-l:#e2c074;
--line:#e6d9bf;--terra:#c2604a;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif;color:var(--ink);
background:#efe6d3;line-height:1.95;font-size:16px;-webkit-font-smoothing:antialiased;}
.page{max-width:820px;margin:0 auto;background:var(--cream);box-shadow:0 0 60px rgba(90,70,30,.15);}
section{padding:40px 56px;border-bottom:1px solid var(--line);}
h1,h2,h3{font-family:"Songti SC","Noto Serif SC",serif;font-weight:700;line-height:1.5;color:var(--ink);}
.hero{text-align:center;padding:64px 56px 48px;
background:radial-gradient(circle at 50% 0%,#fdf8ec 0%,#f5ecd7 70%,#efe2c4 100%);}
.hero .kicker{font-family:Georgia,serif;font-style:italic;letter-spacing:5px;color:var(--gold);
font-size:13px;margin-bottom:14px;}
.hero h1{font-size:34px;letter-spacing:3px;margin-bottom:10px;}
.hero .sub{font-size:15px;color:var(--sub);letter-spacing:2px;}
.hero .art{margin:26px auto 4px;max-width:340px;border-radius:14px;overflow:hidden;
box-shadow:0 8px 30px rgba(90,70,30,.25);border:1px solid var(--line);}
.hero .art img{display:block;width:100%;height:auto;}
@media(max-width:640px){.hero .art{max-width:240px;}}
.lead-sec{padding-top:8px;}
.lead{background:var(--paper);border:1px solid var(--line);border-left:4px solid var(--gold);
border-radius:0 14px 14px 0;padding:24px 28px;margin:6px 0 4px;font-family:"Songti SC","Noto Serif SC",serif;
font-size:17px;line-height:2;}
.sec-tag{display:flex;align-items:center;gap:12px;margin-bottom:6px;}
.sec-num{font-family:Georgia,serif;font-style:italic;font-size:14px;color:var(--gold);
letter-spacing:2px;white-space:nowrap;}
.sec-line{flex:1;height:1px;background:linear-gradient(90deg,var(--gold-l),transparent);}
h2{font-size:23px;margin-bottom:18px;}
h3{font-size:17px;margin:22px 0 10px;color:#5d5240;}
h3::before{content:"— ";color:var(--gold-l);}
p{margin-bottom:14px;}
strong{color:var(--gold);font-weight:600;}
ul{margin:0 0 16px 0;list-style:none;}
li{margin-bottom:12px;padding-left:1.1em;position:relative;}
li::before{content:"\\25C6";position:absolute;left:0;color:var(--gold-l);font-size:11px;top:.5em;}
.note{background:var(--paper);border:1px dashed var(--gold-l);border-radius:12px;
padding:14px 20px;margin:12px 0;font-size:14.5px;color:#5d5240;}
table{width:100%;border-collapse:collapse;margin:14px 0 22px;font-size:14.5px;
background:var(--paper);border:1px solid var(--line);}
th,td{padding:10px 14px;text-align:left;vertical-align:top;line-height:1.8;
border-bottom:1px solid var(--line);}
th{background:#f3e9d2;font-family:"Songti SC","Noto Serif SC",serif;color:#5d5240;
font-weight:700;white-space:nowrap;}
tr:last-child td{border-bottom:none;}
.disclaimer{background:var(--paper);border:1px solid var(--line);border-radius:14px;
padding:16px 24px;margin:20px 0 4px;font-size:14px;color:var(--sub);text-align:center;}
@media(max-width:640px){body{font-size:15px;}.page{box-shadow:none;}
section{padding:28px 22px;}.hero{padding:44px 22px 36px;}.hero h1{font-size:27px;}}
@media print{body{background:#fff;font-size:12.5pt;}.page{box-shadow:none;max-width:none;}
section{padding:20pt 0;border-bottom:none;page-break-inside:avoid;}
.hero{background:none;padding:0 0 20pt;}h2{page-break-after:avoid;}h3{page-break-after:avoid;}}
"""


def _inline(text: str) -> str:
    """转义 HTML 后映射行内 **加粗**。"""
    esc = html.escape(text, quote=False)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", esc)


def _is_disclaimer(text: str) -> bool:
    return all(m in text for m in DISCLAIMER_MARKERS)


def _split_row(row: str) -> list[str]:
    """| a | b | → [a, b]（管道表格行切分）。"""
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _is_sep_row(row: str) -> bool:
    """|---|---| 分隔行判定。"""
    cells = _split_row(row)
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells)


def _table_html(rows: list[str]) -> str:
    """连续管道行 → <table>；首行表头，分隔行丢弃。"""
    rows = [r for r in rows if not _is_sep_row(r)]
    if not rows:
        return ""
    head = "".join(f"<th>{_inline(c)}</th>" for c in _split_row(rows[0]))
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in _split_row(r)) + "</tr>"
        for r in rows[1:])
    return f"<table><tr>{head}</tr>{body}</table>"


def _img_data_uri(image_path: str | Path) -> str:
    """图片文件 → data URI（base64 内嵌，保持单文件 HTML 可转发/离线）。"""
    ip = Path(image_path)
    mime = mimetypes.guess_type(ip.name)[0] or "image/jpeg"
    b64 = base64.b64encode(ip.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def render_report_html(md_text: str, *, theme: str | None = None,
                       image_path: str | Path | None = None) -> str:
    """report.md 干净版 → 单文件 HTML。theme 缺省时从「解读主题：X」行提取。
    image_path 给定时在 hero 区内嵌画作（base64）。"""
    body_md = md_text.split(APPENDIX_HEADING, 1)[0]
    lines = body_md.replace("\r\n", "\n").split("\n")
    hero_title, hero_sub = "曼陀罗解读报告", ""
    chunks: list[str] = []
    lead_parts: list[str] = []
    in_lead = True
    sec_no = 0
    i = 0
    # 首两行「曼陀罗解读报告」「解读主题：X」是 hero 的 md 影子，消费掉不进正文
    if lines and lines[0].strip() == hero_title:
        i = 1
        if len(lines) > 1:
            m = re.match(r"解读主题[:：]\s*(.+)", lines[1].strip())
            if m:
                hero_sub = m.group(1).strip()
                i = 2
    while i < len(lines):
        line = lines[i].rstrip()
        i += 1
        if not line.strip() or line.strip() == "---":
            continue
        if line.startswith("### "):
            in_lead = False
            chunks.append(f"<h3>{_inline(line[4:].strip())}</h3>")
            continue
        if line.startswith("## "):
            in_lead = False
            sec_no += 1
            chunks.append(
                f'<div class="sec-tag"><span class="sec-num">{sec_no:02d}</span>'
                f'<span class="sec-line"></span></div><h2>{_inline(line[3:].strip())}</h2>')
            continue
        if line.lstrip().startswith("- "):
            in_lead = False
            items = [_inline(line.lstrip()[2:].strip())]
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                items.append(_inline(lines[i].lstrip()[2:].strip()))
                i += 1
            chunks.append("<ul>" + "".join(f"<li>{it}</li>" for it in items) + "</ul>")
            continue
        if line.lstrip().startswith("> "):
            in_lead = False
            chunks.append(f'<p class="note">{_inline(line.lstrip()[2:].strip())}</p>')
            continue
        if line.lstrip().startswith("|"):
            in_lead = False
            rows = [line.strip()]
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            tbl = _table_html(rows)
            if tbl:
                chunks.append(tbl)
            continue
        # 普通段落
        if _is_disclaimer(line.strip()):
            chunks.append(f'<p class="disclaimer">{_inline(line.strip())}</p>')
        elif in_lead:
            lead_parts.append(_inline(line.strip()))
            continue
        else:
            chunks.append(f"<p>{_inline(line.strip())}</p>")
    if lead_parts:
        lead_html = "".join(f"<p>{p}</p>" for p in lead_parts)
        # lead 段插在 hero 之后：hero 未输出，直接作为首段
        chunks.insert(0, f'<div class="lead">{lead_html}</div>')
    if hero_sub == "" and theme:
        hero_sub = theme
    if hero_sub == "":
        for ln in lines[:3]:
            m = re.match(r"解读主题[:：]\s*(.+)", ln.strip())
            if m:
                hero_sub = m.group(1).strip()
                break
    title = hero_title + (f" · {hero_sub}" if hero_sub else "")
    art_html = (f'<div class="art"><img src="{_img_data_uri(image_path)}" alt="曼陀罗画作"></div>'
                if image_path else "")
    # 全部正文一个 section 流：鎏金章节号给出视觉分段；lead-sec 收窄首节上距
    lead_cls = " lead-sec" if lead_parts else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">
<section class="hero">
<div class="kicker">MANDALA READING REPORT</div>
<h1>{html.escape(hero_title)}</h1>
<div class="sub">{html.escape(hero_sub)}</div>
{art_html}
</section>
<section class="first{lead_cls}">
{"".join(chunks)}
</section>
</div>
</body>
</html>
"""
