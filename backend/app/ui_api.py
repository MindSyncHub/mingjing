"""本地工作台 UI 适配层（spec: docs/specs/ui-v1.md，D-111）。

只做四件事：扫描 runs/ 出报告列表、伺服/编辑/重渲单个报告产物、追溯链逐步输入/输出查看、跑单图输入预处理流水线。
零业务逻辑——所有质量判断、渲染、校验仍在原工作流内。
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"
DEFAULT_PREP_OUT = REPO_ROOT / "state/input-prep-ui"

router = APIRouter(prefix="/ui", tags=["ui"])

# g1 中「需要人工复核」的计数字段：>0 即标红（UI-003）
_G1_FLAG_FIELDS = (
    "orphan_accepted_claims", "forbidden_phrases", "marker_line_evidence_claims",
    "pending_terms_used_in_body", "exemplar_copy_spans", "unanchored_statements",
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _g1_summary(g1: dict[str, Any] | None) -> dict[str, Any]:
    """把 run.json 的 g1 块压成列表页/详情页共用的计数摘要。"""
    g1 = g1 or {}
    flags = {k: len(g1.get(k) or []) for k in _G1_FLAG_FIELDS}
    return {
        "passed": bool(g1.get("passed")),
        "accepted_claim_count": g1.get("accepted_claim_count", 0),
        "flags": flags,
        "needs_review": sum(flags.values()) > 0 or not bool(g1.get("passed", False)),
        "raw": g1,
    }


def _report_summary(run_dir: Path) -> dict[str, Any]:
    meta = _load_json(run_dir / "run.json")
    inp = meta.get("input") or {}
    return {
        "report_id": meta.get("report_id") or run_dir.name,
        "status": meta.get("status", "unknown"),
        "theme": inp.get("theme") or "",
        "started_at": meta.get("started_at", ""),
        "elapsed_ms": meta.get("elapsed_ms"),
        "edited_at": meta.get("edited_at"),
        "pipeline": meta.get("pipeline") or "",
        "g1": _g1_summary(meta.get("g1")),
        "has_report_html": (run_dir / "report.html").is_file(),
        "has_report_md": (run_dir / "report.md").is_file(),
        "has_audit_md": (run_dir / "audit.md").is_file(),
    }


def list_reports(*, runs_root: Path = DEFAULT_RUNS_ROOT) -> list[dict[str, Any]]:
    """扫描 runs/ 返回摘要列表，按 started_at 倒序（spec /ui/reports）。"""
    if not runs_root.is_dir():
        return []
    rows = [_report_summary(d) for d in runs_root.iterdir() if d.is_dir() and (d / "run.json").is_file()]
    rows.sort(key=lambda r: r["started_at"], reverse=True)
    return rows


def get_run_dir(report_id: str, *, runs_root: Path = DEFAULT_RUNS_ROOT) -> Path:
    """report_id 定位 run 目录；不存在 404。id 只用文件名合法字符，不做路径展开信任。"""
    rid = (report_id or "").strip()
    if not rid or "/" in rid or "\\" in rid or rid.startswith("."):
        raise HTTPException(status_code=404, detail="报告不存在")
    run_dir = runs_root / rid
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="报告不存在")
    return run_dir


def get_report_detail(report_id: str, *, runs_root: Path = DEFAULT_RUNS_ROOT) -> dict[str, Any]:
    """run.json 摘要 + report.md 全文（spec /ui/reports/{id}）。"""
    run_dir = get_run_dir(report_id, runs_root=runs_root)
    meta = _load_json(run_dir / "run.json")
    md_path = run_dir / "report.md"
    return {
        **_report_summary(run_dir),
        "models": meta.get("models") or {},
        "token_usage": meta.get("token_usage") or {},
        "timings_ms": meta.get("timings_ms") or {},
        "warnings": meta.get("warnings") or [],
        "image_path": (meta.get("input") or {}).get("image_path") or "",
        "report_md": md_path.read_text(encoding="utf-8") if md_path.is_file() else "",
        "audit_md": (run_dir / "audit.md").read_text(encoding="utf-8")
                    if (run_dir / "audit.md").is_file() else "",
    }


def _render_to(run_dir: Path) -> int:
    """report.md → report.html（D-110 确定性渲染），返回渲染毫秒。"""
    md_path = run_dir / "report.md"
    if not md_path.is_file():
        raise HTTPException(status_code=422, detail="report.md 不存在，无法渲染")
    from app.workflows.report_gen.render import render_report_html
    started = time.perf_counter()
    html = render_report_html(md_path.read_text(encoding="utf-8"))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    (run_dir / "report.html").write_text(html, encoding="utf-8")
    return elapsed_ms


def save_report_md(report_id: str, md_text: str, *, runs_root: Path = DEFAULT_RUNS_ROOT) -> dict[str, Any]:
    """保存编辑后的 md 并自动重渲，run.json 记 edited_at（spec /ui/reports/{id}/report-md）。"""
    if not isinstance(md_text, str) or not md_text.strip():
        raise HTTPException(status_code=422, detail="report_md 不能为空")
    run_dir = get_run_dir(report_id, runs_root=runs_root)
    (run_dir / "report.md").write_text(md_text, encoding="utf-8")
    render_ms = _render_to(run_dir)
    meta_path = run_dir / "run.json"
    meta = _load_json(meta_path)
    meta["edited_at"] = datetime.now(timezone.utc).isoformat()
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": True, "render_ms": render_ms, "edited_at": meta["edited_at"]}


def re_render(report_id: str, *, runs_root: Path = DEFAULT_RUNS_ROOT) -> dict[str, Any]:
    run_dir = get_run_dir(report_id, runs_root=runs_root)
    return {"render_ms": _render_to(run_dir)}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def get_trace(report_id: str, *, runs_root: Path = DEFAULT_RUNS_ROOT) -> dict[str, Any]:
    """追溯链全量（spec /ui/reports/{id}/trace，UI-008）：感知→观察→信号→假设→claim + 复核清单。

    全部文件缺失容忍（旧 run 可能缺 perception.md 等），缺什么返回什么，前端按空隐藏。
    """
    run_dir = get_run_dir(report_id, runs_root=runs_root)
    meta = _load_json(run_dir / "run.json")
    g1 = meta.get("g1") or {}
    claims_doc = _load_json(run_dir / "claims.json")
    claims = claims_doc.get("claims") or []
    hypotheses_doc = _load_json(run_dir / "hypotheses.json")
    observations_doc = _load_json(run_dir / "observations.json")
    signals_doc = _load_json(run_dir / "signals.json")
    accepted = [c for c in claims if c.get("status") == "accepted"]
    inp = meta.get("input") or {}
    needs_human = [c for c in claims if c.get("status") == "needs_human"]
    flag_names = ("orphan_accepted_claims", "forbidden_phrases", "marker_line_evidence_claims",
                  "pending_terms_used_in_body", "exemplar_copy_spans", "exemplar_structure_spans",
                  "unanchored_statements")
    return {
        "run_meta": {
            "models": meta.get("models") or {},
            "token_usage": meta.get("token_usage") or {},
            "timings_ms": meta.get("timings_ms") or {},
            "warnings": meta.get("warnings") or [],
            "image_path": inp.get("image_path") or "",
            "theme": inp.get("theme") or "",
        },
        "perception_md": _read_text(run_dir / "perception.md"),
        "observations": observations_doc.get("observations") or [],
        "vision_observations": observations_doc.get("vision_observations") or [],
        "ambiguities": observations_doc.get("vision_ambiguities") or [],
        "questions_for_healer": observations_doc.get("questions_for_healer") or [],
        "signals": {k: signals_doc.get(k) or [] for k in ("blocks", "structures")},
        "hypotheses": {k: hypotheses_doc.get(k) or [] for k in
                       ("direct_pattern_hits", "five_elements", "imbalance_hypotheses",
                        "state_hypotheses", "topic_hypotheses")},
        "claims": {"accepted": accepted, "needs_human": needs_human},
        "g1_flags_detail": {k: g1.get(k) or [] for k in flag_names},
        "report_sourced_md": _read_text(run_dir / "report.sourced.md"),
    }


# ---------- 追溯链逐步输入/输出（UI-012，D-112） ----------

_STEP_TEXT_CAP = 150_000  # 单文件文本伺服上限（localhost 单用户，防误读超大 HTML）

# 三步与 gen_audit.py 实际调用一一对应（D-013 后：生成 → 合规/超纲核查 → 渲染）；
# 程序步给源文件（无独立 prompt 文本）。旧 stage35 架构的 run 仅浏览已落盘文件。
# metric_key = run.json 里 timings_ms/token_usage/models 的步键（渲染步无计量）。
_STEP_META: dict[int, dict[str, Any]] = {
    1: {"name": "报告生成", "ai": True, "prompt": "10-generate.md", "metric_key": "generate",
        "input_note": "VL 模型（qwen3-vl-plus）；手册原文 + 主题 + 画作，疗愈师语态（D-012）",
        "out": [("report.md", "解读报告初稿")]},
    2: {"name": "合规与超纲核查", "ai": True, "prompt": "20-audit.md", "metric_key": "audit",
        "input_note": "VL 模型；图 + 手册 + 直断法库 + 初稿；只审合规红线 + 采掘超纲（D-013）",
        "out": [("audit.md", "合规核查 + 超纲清单（疗愈师终审草稿）")]},
    3: {"name": "渲染交付", "ai": False, "program": ("render.py", "render_report_html（D-110）"),
        "metric_key": None, "input_note": "report.md（上一步初稿），规则映射不经 LLM",
        "out": [("report.html", "单文件 HTML（米色鎏金主题）")]},
}

_SRC_ROOT = REPO_ROOT / "backend" / "app" / "workflows" / "report_gen"


def _cap_text(text: str) -> str:
    return text if len(text) <= _STEP_TEXT_CAP else text[:_STEP_TEXT_CAP] + "\n…[截断]"


def get_step_detail(report_id: str, step: int, *, runs_root: Path = DEFAULT_RUNS_ROOT) -> dict[str, Any]:
    """追溯链单步的输入与输出全文（spec /ui/reports/{id}/step/{n}，UI-012）。

    LLM 步输入 = prompts/ 落盘的 prompt 原文（v0.6.7 起；旧 run 返回 missing_hint）；
    程序步输入 = 现行源码文件（固定白名单映射，不接受任意路径）。
    """
    meta_info = _STEP_META.get(step)
    if meta_info is None:
        raise HTTPException(status_code=404, detail=f"未知步骤：{step}（链路共 3 步）")
    run_dir = get_run_dir(report_id, runs_root=runs_root)
    if meta_info["ai"]:
        prompt_path = run_dir / "prompts" / meta_info["prompt"]
        content = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else None
        inp: dict[str, Any] = {
            "kind": "prompt", "label": f"prompt 原文：prompts/{meta_info['prompt']}",
            "path": str(prompt_path), "content": _cap_text(content) if content is not None else None,
            "note": meta_info.get("input_note") or "",
            "missing_hint": None if content is not None
                else "该 run 未落盘此 prompt（可能是旧 stage35 架构的 run，仅支持浏览已落盘文件）",
        }
    else:
        fname, hint = meta_info["program"]
        src = _SRC_ROOT / fname
        content = src.read_text(encoding="utf-8") if src.is_file() else None
        inp = {"kind": "program", "label": f"程序文件：{fname}（{hint}）",
               "path": str(src), "content": _cap_text(content) if content is not None else None,
               "note": "显示的是代码现行版本，历史版本见 git", "missing_hint": None}
    outputs = []
    for fname, label in meta_info["out"]:
        fpath = run_dir / fname
        outputs.append({
            "label": f"{label}：{fname}", "path": str(fpath),
            "content": _cap_text(fpath.read_text(encoding="utf-8")) if fpath.is_file() else None,
            "missing_hint": None if fpath.is_file() else "文件不存在（该步可能未执行或已丢失）",
        })
    return {"step": step, "name": meta_info["name"], "ai": meta_info["ai"],
            "input": inp, "outputs": outputs}


def get_pipeline(report_id: str, *, runs_root: Path = DEFAULT_RUNS_ROOT) -> dict[str, Any]:
    """链路结构元数据下发（spec /ui/reports/{id}/pipeline，UI-013）：前端不复制链路口径。

    gen-audit-v1 run：返回三步（_STEP_META 顺序），逐步带模型/耗时/token/产物存在性。
    其他（旧 stage35 架构）：legacy 标记 + 降级提示，前端走历史浏览路径。
    """
    run_dir = get_run_dir(report_id, runs_root=runs_root)
    meta = _load_json(run_dir / "run.json")
    pipeline = meta.get("pipeline") or ""
    if pipeline != "gen-audit-v1":
        return {"pipeline": pipeline or "stage35", "legacy": True,
                "note": "旧 stage35 架构的 run：七步链路仅历史浏览，以已落盘文件为准",
                "steps": []}
    timings = meta.get("timings_ms") or {}
    tokens = meta.get("token_usage") or {}
    models = meta.get("models") or {}
    steps = []
    for n, info in _STEP_META.items():
        key = info.get("metric_key")
        tok = tokens.get(key) if key else None
        steps.append({
            "n": n, "name": info["name"], "ai": info["ai"],
            "tool": (models.get(key) if key else None) or "程序 · 不经 AI",
            "input_note": info.get("input_note") or "",
            "cost_ms": timings.get(key) if key else None,
            "tokens": {"prompt": tok.get("prompt_tokens"), "completion": tok.get("completion_tokens"),
                       "total": tok.get("total_tokens")} if tok else None,
            "outputs": [{"file": fname, "label": label, "exists": (run_dir / fname).is_file()}
                        for fname, label in info["out"]],
        })
    return {"pipeline": pipeline, "legacy": False,
            "elapsed_ms": meta.get("elapsed_ms"), "token_total": tokens.get("total") or None,
            "steps": steps}


def report_image_path(report_id: str, *, runs_root: Path = DEFAULT_RUNS_ROOT) -> Path:
    """画作原图路径（绝对路径 + 必须存在，spec /ui/reports/{id}/image）。"""
    detail_image = (get_run_dir(report_id, runs_root=runs_root) / "run.json").exists()
    if not detail_image:
        raise HTTPException(status_code=404, detail="报告不存在")
    meta = _load_json(get_run_dir(report_id, runs_root=runs_root) / "run.json")
    image_path = Path((meta.get("input") or {}).get("image_path") or "")
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="画作图片不存在")
    return image_path


# ---------- 输入预处理流水线（WF-INPUT-PREP 单图版，不经 AI） ----------

def run_input_prep(photo: UploadFile, *, out_dir: Path = DEFAULT_PREP_OUT) -> dict[str, Any]:
    """单图流水线：矫正→裁切→基准圆检测→圈界提议（input-prep spec §2.1）。

    产物落 out_dir：定稿图 {stem}_final.jpg（叠加绿基准圆 + 蓝圈界）、参数 JSON。
    返回 image_path + ring_params（cx/cy/radius/r1_ratio/r2_ratio）+ overlay 伺服路径。
    """
    import cv2
    from app.workflows.input_prep.crop import crop_to_painting
    from app.workflows.input_prep.detection import detect_baseline
    from app.workflows.input_prep.rectify import RectifyError, rectify

    def _decode(data: bytes):
        from PIL import Image, ImageOps
        import io, numpy as np
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            return cv2.cvtColor(np.array(im.convert('RGB')), cv2.COLOR_RGB2BGR)
    from app.workflows.input_prep.rings import propose_rings

    out_dir.mkdir(parents=True, exist_ok=True)
    data = photo.file.read()
    if not data:
        raise HTTPException(status_code=422, detail="照片为空")
    stem = Path(photo.filename or "photo").stem or "photo"
    src_path = out_dir / f"{stem}_raw{Path(photo.filename or '.jpg').suffix or '.jpg'}"
    src_path.write_bytes(data)
    try:
        img = _decode(data)
        r = rectify(img)
        c = crop_to_painting(r.image, r.circle_hint)
        b = detect_baseline(c.image, c.circle_hint)
        prop = propose_rings(c.image, b.circle.x, b.circle.y, b.circle.r)
    except RectifyError as exc:
        raise HTTPException(status_code=422, detail=f"输入预处理失败: {exc}") from exc

    overlay = c.image.copy()
    cv2.circle(overlay, (round(b.circle.x), round(b.circle.y)), round(b.circle.r), (0, 200, 0), 3)
    for rr in (prop.r1, prop.r2):
        cv2.circle(overlay, (round(b.circle.x), round(b.circle.y)), round(rr), (230, 120, 0), 4)
    final_path = out_dir / f"{stem}_final.jpg"
    cv2.imwrite(str(final_path), overlay)
    params = {
        "cx": round(b.circle.x, 1), "cy": round(b.circle.y, 1), "radius": round(b.circle.r, 1),
        "r1_ratio": round(prop.r1 / b.circle.r, 3), "r2_ratio": round(prop.r2 / b.circle.r, 3),
        "clarity": round(prop.clarity, 2), "fallback": prop.fallback,
    }
    (out_dir / f"{stem}_params.json").write_text(
        json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "image_path": str(final_path),
        "ring_params": params,
        "overlay_url": f"/ui/prep-image/{final_path.name}",
        "rectified": r.rectified,
        "axis_ratio": round(b.axis_ratio, 3),
    }


# ---------- 审核备注（v0.1.2）：review.json 随 run 目录走 ----------

import re as _re

_REVIEW_KEY_RE = _re.compile(r"^(general|(obs|claim|hyp|flag|sig):[\w.\-:]{0,119}[\w.\-])$")


def get_review(report_id: str, *, runs_root: Path = DEFAULT_RUNS_ROOT) -> dict[str, Any]:
    """审核备注全量（spec /ui/reports/{id}/review GET）；无 review.json 返回空 items。"""
    run_dir = get_run_dir(report_id, runs_root=runs_root)
    doc = _load_json(run_dir / "review.json")
    items = doc.get("items")
    return {"report_id": report_id, "items": items if isinstance(items, dict) else {},
            "updated_at": doc.get("updated_at") or ""}


def upsert_review_item(report_id: str, key: str, checked: bool | None, note: str | None,
                       *, runs_root: Path = DEFAULT_RUNS_ROOT) -> dict[str, Any]:
    """单条 upsert（spec /ui/reports/{id}/review PUT）。checked/note 均可单独更新；传 None 不动该项。"""
    key = (key or "").strip()
    if not _REVIEW_KEY_RE.match(key):
        raise HTTPException(status_code=422, detail=f"key 不合法: {key!r}")
    run_dir = get_run_dir(report_id, runs_root=runs_root)
    path = run_dir / "review.json"
    doc = _load_json(path)
    items = doc.get("items") if isinstance(doc.get("items"), dict) else {}
    entry = items.get(key) if isinstance(items.get(key), dict) else {}
    if checked is not None:
        entry["checked"] = bool(checked)
    if note is not None:
        note = note.strip()
        if note:
            entry["note"] = note
        else:
            entry.pop("note", None)  # 清空备注 = 删除键
    if not entry.get("checked") and not entry.get("note"):
        items.pop(key, None)  # 未勾且无备注 → 不占条目（勾=False 也算未勾）
    else:
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        items[key] = entry
    doc = {"items": items, "updated_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"saved": True, "key": key, "entry": items.get(key) or {}}


# ---------- HTTP 路由 ----------

@router.get("/reports")
async def ui_reports() -> list[dict[str, Any]]:
    return list_reports()


@router.get("/reports/{report_id}")
async def ui_report_detail(report_id: str) -> dict[str, Any]:
    return get_report_detail(report_id)


@router.get("/reports/{report_id}/perception-score")
async def ui_perception_score(report_id: str) -> dict[str, Any]:
    """感知记分牌（D-119）：该 run 的 perception.md × 对应真值表自动对分。"""
    from app.perception_eval import score_run
    run_dir = get_run_dir(report_id)
    meta = _load_json(run_dir / "run.json")
    image_name = Path(meta.get("input", {}).get("image_path", "")).name
    result = score_run(run_dir, image_name)
    if result is None:
        return {"enabled": False, "reason": "该图暂无真值表，未启用自动判分（eval/golden-perception/ 补 truth.json 后生效）"}
    return {"enabled": True, **result}


@router.get("/reports/{report_id}/html")
async def ui_report_html(report_id: str):
    run_dir = get_run_dir(report_id)
    html_path = run_dir / "report.html"
    if not html_path.is_file():
        raise HTTPException(status_code=404, detail="渲染产物不存在，请重新渲染")
    return FileResponse(html_path, media_type="text/html")


@router.get("/reports/{report_id}/image")
async def ui_report_image(report_id: str):
    return FileResponse(report_image_path(report_id))


@router.put("/reports/{report_id}/report-md")
async def ui_save_report_md(report_id: str, body: dict[str, Any]) -> dict[str, Any]:
    md_text = body.get("report_md")
    if not isinstance(md_text, str) or not md_text.strip():
        raise HTTPException(status_code=422, detail="report_md 不能为空")
    return save_report_md(report_id, md_text)


@router.get("/reports/{report_id}/review")
async def ui_get_review(report_id: str) -> dict[str, Any]:
    return get_review(report_id)


@router.put("/reports/{report_id}/review")
async def ui_put_review(report_id: str, body: dict[str, Any]) -> dict[str, Any]:
    return upsert_review_item(report_id, body.get("key") or "",
                              body.get("checked"), body.get("note"))


@router.get("/reports/{report_id}/step/{step}")
async def ui_report_step(report_id: str, step: int) -> dict[str, Any]:
    return get_step_detail(report_id, step)


@router.get("/reports/{report_id}/pipeline")
async def ui_report_pipeline(report_id: str) -> dict[str, Any]:
    return get_pipeline(report_id)


@router.get("/reports/{report_id}/trace")
async def ui_report_trace(report_id: str) -> dict[str, Any]:
    return get_trace(report_id)


@router.post("/reports/{report_id}/re-render")
async def ui_re_render(report_id: str) -> dict[str, Any]:
    return re_render(report_id)


@router.post("/input-prep/run")
async def ui_input_prep_run(photo: UploadFile) -> dict[str, Any]:
    return run_input_prep(photo)


@router.get("/prep-image/{name}")
async def ui_prep_image(name: str):
    """预处理叠加图伺服（文件名白名单校验，不开放任意路径）。"""
    safe = Path(name).name
    path = DEFAULT_PREP_OUT / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)
