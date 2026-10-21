"""FastAPI 入口：输入预处理、主 Agent 调度层（/dispatch）、报告生成与报告问答。"""
import json
from typing import Optional

from fastapi import Body, FastAPI, Form, HTTPException, UploadFile

from app.config import settings
from app.core.agent import UnknownAgentError, resolve_agent
from app.core.guard import check_input
from app.workflows.report_gen.gen_audit import GenAuditError, run_gen_audit_from_path
from app.workflows.report_qa import answer_question, list_turns

app = FastAPI(title="mingjing-backend", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/input-prep")
async def input_prep(photo: UploadFile) -> dict:
    """接收曼陀罗照片，原样存盘并返回保存路径（后续矫正/三圈标记在 workflows/input_prep 内）。"""
    import os

    data = await photo.read()
    dest = settings.data_dir + f"/input-prep/{photo.filename}"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return {"received": photo.filename, "bytes": len(data), "saved_to": dest}


def _report_gen_payload(payload: dict) -> dict:
    theme = (payload.get("theme") or "").strip()
    if not theme:
        raise HTTPException(status_code=422, detail="请先填写来访者主题")

    guard_text = theme
    manual = payload.get("manual_features") or ""
    if isinstance(manual, dict):
        guard_text += " " + json.dumps(manual, ensure_ascii=False)
    elif manual:
        guard_text += " " + str(manual)
    guard = check_input(guard_text)
    if guard.blocked or guard.case_risk:
        return {"status": "blocked", "human_review_required": True,
                "category": "crisis_case_risk" if guard.case_risk else guard.category,
                "message": guard.message}

    image_path = (payload.get("image_path") or "").strip()
    if not image_path:
        raise HTTPException(status_code=422, detail="请提供 image_path（本版不支持纯手动输入）")

    ring_params = payload.get("ring_params") or None
    if isinstance(ring_params, str):
        try:
            ring_params = json.loads(ring_params)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"ring_params 不是合法 JSON: {exc}") from exc

    try:
        run_dir = run_gen_audit_from_path(image_path=image_path, theme=theme,
                                          client=(payload.get("client") or "").strip(),
                                          ring_params=ring_params)
    except GenAuditError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    report_md = (run_dir / "report.md").read_text(encoding="utf-8")
    audit_md = (run_dir / "audit.md").read_text(encoding="utf-8")
    context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
    return {"status": "ok", "report_id": run_dir.name, "report": report_md,
            "audit": audit_md, "context": context, "run_dir": str(run_dir)}


def _report_qa_payload(payload: dict) -> dict:
    report_id = (payload.get("report_id") or "").strip()
    user_question = (payload.get("user_question") or "").strip()
    if not report_id:
        raise HTTPException(status_code=422, detail="缺少 report_id")
    if not user_question:
        raise HTTPException(status_code=422, detail="缺少 user_question")
    scenario = payload.get("scenario") or "advisor"
    conversation_history = payload.get("conversation_history") or None
    if isinstance(conversation_history, str):
        try:
            conversation_history = json.loads(conversation_history)
        except json.JSONDecodeError:
            conversation_history = None
    try:
        return answer_question(report_id=report_id, user_question=user_question,
                               scenario=scenario, conversation_history=conversation_history,
                               action=payload.get("action") or None,
                               override_type=payload.get("override_type") or None,
                               supplement=payload.get("supplement") or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/dispatch")
async def dispatch(body: dict = Body(...)) -> dict:
    """主 Agent 调度层：人工显式指定 agent（report_gen / report_qa），薄路由到对应子 Agent。"""
    try:
        agent = resolve_agent(body.get("agent"))
    except UnknownAgentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = body.get("payload") or {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload 必须是对象")
    if agent == "report_gen":
        return _report_gen_payload(payload)
    return _report_qa_payload(payload)


@app.post("/report-gen")
async def report_gen(image_path: str = Form(...), theme: str = Form(...),
                     ring_params: Optional[str] = Form(None),
                     manual_features: Optional[str] = Form(None)) -> dict:
    return _report_gen_payload({"image_path": image_path, "theme": theme,
                                "ring_params": ring_params, "manual_features": manual_features})


@app.post("/report-qa")
async def report_qa(report_id: str = Form(...), user_question: str = Form(...),
                    scenario: str = Form("advisor"),
                    conversation_history: Optional[str] = Form(None),
                    action: Optional[str] = Form(None),
                    override_type: Optional[str] = Form(None),
                    supplement: Optional[str] = Form("")) -> dict:
    return _report_qa_payload({"report_id": report_id, "user_question": user_question,
                               "scenario": scenario, "conversation_history": conversation_history,
                               "action": action, "override_type": override_type,
                               "supplement": supplement})


@app.get("/report-qa/turns")
async def report_qa_turns(report_id: str) -> dict:
    """问答历史回读（spec 2.6）：只读 qa/ 子目录，按轮次升序；无效 report_id 返回空数组。"""
    report_id = (report_id or "").strip()
    if not report_id:
        raise HTTPException(status_code=422, detail="缺少 report_id")
    return {"report_id": report_id, "turns": list_turns(report_id=report_id)}


# ---- 本地工作台 UI（D-111，spec: docs/specs/ui-v1.md）----
from app.ui_api import REPO_ROOT as _UI_ROOT, router as _ui_router  # noqa: E402

app.include_router(_ui_router)

_UI_DIR = _UI_ROOT / "ui"
if _UI_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    class _NoCacheStaticFiles(StaticFiles):
        """本地工作台单用户使用：UI 文件禁缓存，避免浏览器用旧版 app.js 导致新功能不可见。"""

        async def get_response(self, path: str, scope):  # type: ignore[override]
            resp = await super().get_response(path, scope)
            ctype = resp.headers.get("content-type", "")
            if ctype.startswith(("text/html", "text/css")) or "javascript" in ctype:
                resp.headers["Cache-Control"] = "no-store"
            return resp

    # 最后注册：API 路由先匹配，静态页兜底 /（spec 工程层 3.1）
    app.mount("/", _NoCacheStaticFiles(directory=str(_UI_DIR), html=True), name="ui")
