"""D-110 渲染步：report.md → 单文件 HTML 的确定性映射测试。"""
from app.workflows.report_gen.render import render_report_html

SAMPLE = """曼陀罗解读报告
解读主题：自我成长与当下状态

**这是一幅根已经扎稳的画。** 你有真实的成长意愿。

## 画面第一眼：一片沉得住气的绿与暖

先看整体透出来的气。

- **饱满**：各圈元素填排密实。
- **暖亮**：明黄与橙黄铺出大面积底色。

### 笔触里藏着作画时的呼吸

彩铅的排线是有记忆的。

## 总评

画已经替你作证。

以上是能量层面的参考，不是诊断，AI 是辅助工具，最终判断在疗愈师。

---

## 待疗愈师核对

| Claim ID | 内容 |
|---|---|
| C-007 | 置信度 0.40 低于 0.5 |
"""


def test_render_maps_hero_lead_sections_disclaimer():
    out = render_report_html(SAMPLE)
    # hero：标题与主题，且主题不重复进 lead
    assert "<h1>曼陀罗解读报告</h1>" in out
    assert '<div class="sub">自我成长与当下状态</div>' in out
    lead = out.split('<div class="lead">')[1].split("</div>")[0]
    assert "解读主题" not in lead and "曼陀罗解读报告" not in lead
    assert "根已经扎稳的画" in lead
    # 章节号与标题
    assert '<span class="sec-num">01</span>' in out
    assert '<span class="sec-num">02</span>' in out
    assert "<h2>画面第一眼：一片沉得住气的绿与暖</h2>" in out
    assert "<h3>笔触里藏着作画时的呼吸</h3>" in out
    # 列表与加粗
    assert "<li><strong>饱满</strong>" in out
    # 免责声明 → 免责块
    assert 'class="disclaimer"' in out and "不是诊断" in out


def test_render_excludes_appendix_and_is_single_file():
    out = render_report_html(SAMPLE)
    assert "待疗愈师核对" not in out
    assert "C-007" not in out
    # 单文件：样式内联、无外链、viewport 在位（移动端验收 ENG-CLI-005）
    assert "<style>" in out and "http" not in out.split("<style>")[1].split("</style>")[1]
    assert 'name="viewport"' in out
    # 打印适配（D-109：浏览器打印 = PDF）
    assert "@media print" in out


def test_render_is_deterministic_and_escapes_html():
    out1 = render_report_html(SAMPLE)
    out2 = render_report_html(SAMPLE)
    assert out1 == out2
    out = render_report_html("## 章节\n\n含有 <script> 的段落。")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_render_falls_back_when_title_line_absent():
    out = render_report_html("## 只有正文\n\n没有标题行的报告。")
    assert "<h1>曼陀罗解读报告</h1>" in out
    assert "<h2>只有正文</h2>" in out
