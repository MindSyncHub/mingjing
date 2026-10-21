"""生成+校验（gen-audit）报告生成架构——2026-10-13 MindSyncHub拍板方案乙，替代 stage35 转译链。

盲测证据（eval-results/blind-2026-10-cases/case-001、002 评分表）：
- stage35（视觉→自然语言→结构化→证据门）识别三轮互矛盾、手册直断全漏、主题核心被证据门拦死；
- 自由生成（图+手册+主题）+ 独立校验臂（图+手册+初稿→逐条审计表）是最优自家方案；
- 本体论从"拦截门禁"改当"事后尺子"：校验臂额外加载知识库结构化直断法库（D-01~D-06）作检查清单。

D-013（2026-10-14）审计臂管辖权收窄：只审合规红线（诊断/承诺/负向打压/危机未转介），
解读对错归疗愈师终审（终审实测：审计臂幻觉判定假阳性率 94%）；
与知识库对不上的论断不判错，归为「超纲」采掘（分流：知识库候选/疑似推理错误/拿不准），
超纲清单是知识库增强的矿源——审计臂从找错员改为合规员+采掘员。

产物（与 ui_api / report_qa 兼容的 run 目录）：
    runs/<report_id>/report.md      报告正文
    runs/<report_id>/audit.md       合规核查 + 超纲清单（疗愈师终审草稿，D-013）
    runs/<report_id>/report.html    渲染版
    runs/<report_id>/context.json   report_qa 兼容（linkage 为空，证据链由 audit.md 承担）
    runs/<report_id>/run.json       元数据（pipeline="gen-audit-v1"）
    runs/<report_id>/prompts/       两次调用的 prompt 落盘（可审计）
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.core.llm import REPO_ROOT
from app.workflows.report_gen.render import render_report_html

RANRAN_ROOT = REPO_ROOT.parent.parent

# 手册默认用删案例版（含 11 案例的版本会让模型抄案例句式；盲测已验证删案例版质量）
MANUAL_PATH = Path(os.environ.get(
    "MINGJING_MANUAL_PATH",
    RANRAN_ROOT / "products/aimandala/docs/疗愈体系知识库/20-疗愈体系/20-流派层/10-曼陀罗/90-来源原文/曼陀罗解读手册原文.md"))
# 本体论尺子：知识库结构化直断法库（D-01~D-06，手册「新手解读6式」的确认版）
RULER_PATH = RANRAN_ROOT / "knowledge/healing/术/流派/曼陀罗/直断解读.md"


class GenAuditError(RuntimeError):
    pass


def _data_url(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(image_path.read_bytes()).decode()


def _vl_call(prompt: str, image_path: Path, *, temperature: float = 1) -> tuple[str, dict, int]:
    """单次视觉模型调用（OpenAI 兼容 chat/completions），返回 (文本, usage, 耗时ms)。"""
    if not settings.kimi_api_key.strip():
        raise GenAuditError("缺少 KIMI_API_KEY（视觉模型）；gen-audit 不 fallback，已停止")
    body = {"model": settings.kimi_model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": _data_url(image_path)}},
            ]}], "temperature": temperature}
    t0 = time.perf_counter()
    req = urllib.request.Request(
        settings.kimi_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {settings.kimi_api_key.strip()}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise GenAuditError(f"视觉模型调用失败: {exc}") from exc
    elapsed = int((time.perf_counter() - t0) * 1000)
    usage = payload.get("usage") or {}
    return payload["choices"][0]["message"]["content"], {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens")}, elapsed


def _gen_prompt(theme: str, manual: str) -> str:
    return f"""你是一位资深曼陀罗疗愈师。请结合附件中的《曼陀罗解读手册》方法体系，解读这幅画。
来访者选定的解读主题：「{theme}」。请围绕该主题做聚焦解读。
要求：
1. 按手册的完整个案流程解读（三圈定位 → 五行感知 → 直断特征 → 分圈细读 → 综合画像），层层递进、以疗愈师对来访者说话的口吻成文。

语态要求（疗愈师之声，D-012；比文采更重要，违反即不合格）：
- 像疗愈师坐在来访者对面说话：温和、笃定、有留白；称呼"你"。
- 用状态说话：解读落到来访者能认出的具体时刻或身体感（如"躺下以后脑子还在转"），不堆术语与玄学黑话。
- 句子要慢：短句为主，一次说一两件事；不写长串排比，不写对仗工整的格言金句。
- 克制热情：不用 emoji，不用"亲爱的""灵魂深处""内在宇宙"这类过度修辞，不喊口号；诚实比安慰重要。
- 陪伴而非说服：建议是邀请（"可以试试"），不是命令（"你必须"）；不承诺效果。
2. 只依据画面可见信息 + 手册规则推演，不做医学/心理诊断，不做承诺。
3. 画面上的圆圈标记线是疗愈师圈定三圈的辅助记号，不是画作内容，不计入五行。
4. 直接输出解读正文（Markdown），不要寒暄、不要复述本要求。

《曼陀罗解读手册》原文：
{manual}"""


def _audit_prompt(theme: str, manual: str, ruler: str, draft: str) -> str:
    return f"""你是一名曼陀罗解读报告的合规员与知识采掘员。附件是一幅曼陀罗（三圈已由疗愈师用标记线圈定，标记线不是画作内容）、《曼陀罗解读手册》原文、一份从手册提炼的《直断法库》（D-01~D-06），以及一位疗愈师对这幅画写的解读报告初稿。来访者主题：「{theme}」。

你的任务只有两项：合规核查 + 超纲采掘。**不裁决解读对错**——解读的合理性由疗愈师的"神"拍板（手册原则：以你的神为准）。

1. 合规核查（唯一硬门槛），逐条检查报告是否命中以下红线：
   - 医学/心理诊断（"你有 XX 病/症"式定性）
   - 确定性承诺（"一定会好""肯定有效"）
   - 负向打压表述（让来访者感到被否定、被评判、被恐吓的说法，如"你就是……的人"式盖棺定论）
   - 危机信号未转介（报告涉及自伤/自杀线索却没有提示转人工/专业帮助）
   命中即列出原句+命中哪条红线；均未命中写"合规通过"。

2. 超纲采掘：报告中在手册与直断法库里**找不到依据**的论断，不判错，逐条收进超纲清单。每条给出：
   - 报告原句（照抄，不改写）
   - 画面证据：原句声称的画面特征在图中是否存在（存在/不存在/拿不准）——仅作分流线索，不作判定
   - 最接近的手册条目（有则抄写手册原文句子；没有则写"手册无相关内容"）
   - 分流建议：「知识库候选」（手册未覆盖、值得增强入库）/「疑似推理错误」/「拿不准」

硬规则：
A. 引用手册时必须抄写手册原文句子，禁止编造页码、章节号或不存在的条目。
B. 你自己的画面判断同样可能出错——拿不准就写"拿不准"，不要把猜测写成定论。
C. 本表是疗愈师终审的草稿，不是自动改卷；超纲清单每条的最终归属（入库/改报告/忽略）由疗愈师拍板。

输出格式（Markdown）：
## 合规核查
（命中清单，或"合规通过"）
## 超纲清单
| # | 报告原句 | 画面证据 | 最接近的手册条目 | 分流建议 |
|---|---|---|---|---|
## 总评
（100 字内：这份报告能交付吗，疗愈师终审要重点看哪几条）

《曼陀罗解读手册》原文：
{manual}

《直断法库》（本体尺子）：
{ruler}

---

待核查的解读报告初稿：
{draft}"""


def run_gen_audit(image_path: Path, *, theme: str, client: str = "",
                  runs_root: Path = REPO_ROOT / "runs",
                  original_path: Path | None = None) -> Path:
    """生成+校验 全流程，返回 run 目录。"""
    if not image_path.is_file():
        raise GenAuditError(f"图片不存在: {image_path}")
    if not MANUAL_PATH.is_file():
        raise GenAuditError(f"手册不存在: {MANUAL_PATH}")
    theme = (theme or "").strip()
    if not theme:
        raise GenAuditError("主题为空")

    manual = MANUAL_PATH.read_text(encoding="utf-8")
    ruler = RULER_PATH.read_text(encoding="utf-8") if RULER_PATH.is_file() else "（直断法库缺失，仅用手册原文核查）"

    started_at = datetime.now(timezone.utc).isoformat()
    t_start = time.perf_counter()

    draft, gen_usage, gen_ms = _vl_call(_gen_prompt(theme, manual), image_path)
    audit, audit_usage, audit_ms = _vl_call(_audit_prompt(theme, manual, ruler, draft), image_path)

    elapsed_ms = int((time.perf_counter() - t_start) * 1000)
    report_id = "r" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    run_dir = runs_root / report_id
    run_dir.mkdir(parents=True, exist_ok=False)

    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "10-generate.md").write_text(_gen_prompt(theme, manual), encoding="utf-8")
    (prompts_dir / "20-audit.md").write_text(_audit_prompt(theme, manual, ruler, draft), encoding="utf-8")

    (run_dir / "report.md").write_text(draft.rstrip() + "\n", encoding="utf-8")
    (run_dir / "audit.md").write_text(audit.rstrip() + "\n", encoding="utf-8")
    (run_dir / "report.html").write_text(
        render_report_html(draft, image_path=image_path), encoding="utf-8")
    (run_dir / "context.json").write_text(json.dumps(
        {"report_id": report_id, "linkage": {},
         "note": "gen-audit 架构：证据链在 audit.md（逐条核查表），无 stage35 linkage"},
        ensure_ascii=False, indent=2), encoding="utf-8")

    run_meta = {
        "report_id": report_id,
        "pipeline": "gen-audit-v1",
        "status": "completed",
        "input": {"image_path": str(image_path),
                  "original_path": str(original_path) if original_path else None,
                  "theme": theme, "client": (client or "").strip()},
        "knowledge": {"manual": str(MANUAL_PATH), "ruler": str(RULER_PATH)},
        "models": {"generate": settings.kimi_model, "audit": settings.kimi_model},
        "token_usage": {"generate": gen_usage, "audit": audit_usage,
                        "total": {"total_tokens": (gen_usage.get("total_tokens") or 0)
                                  + (audit_usage.get("total_tokens") or 0)}},
        "timings_ms": {"generate": gen_ms, "audit": audit_ms},
        "started_at": started_at,
        "elapsed_ms": elapsed_ms,
        "warnings": [] if RULER_PATH.is_file() else ["直断法库缺失，校验臂仅用手册原文"],
    }
    (run_dir / "run.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print(f"[gen-audit] {run_dir} 生成{gen_ms}ms+校验{audit_ms}ms", file=sys.stderr)
    return run_dir


def run_gen_audit_from_path(*, image_path: str, theme: str, client: str = "",
                            ring_params: dict | None = None,
                            runs_root: Path = REPO_ROOT / "runs") -> Path:
    """main.py 调用入口。ring_params 兼容旧签名：gen-audit 架构不做程序化圈界，
    三圈由生成臂按手册'以神为准、买定离手'自行划分（标记线图则直接读标记线）。"""
    return run_gen_audit(Path(image_path), theme=theme, client=client, runs_root=runs_root)
