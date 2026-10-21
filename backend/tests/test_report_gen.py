import json


def _fake_run(tmp_path, report_id="R-20260101T000000Z-abc123"):
    run_dir = tmp_path / report_id
    run_dir.mkdir()
    (run_dir / "report.md").write_text("报告正文", encoding="utf-8")
    (run_dir / "audit.md").write_text("合规通过", encoding="utf-8")
    (run_dir / "context.json").write_text(json.dumps(
        {"report_id": report_id, "linkage": {"five_elements": [], "imbalances": [], "states": [], "topics": []}},
        ensure_ascii=False,
    ), encoding="utf-8")
    return run_dir


def test_report_gen_missing_theme(client):
    resp = client.post("/dispatch", json={"agent": "report_gen", "payload": {}})
    assert resp.status_code == 422


def test_report_gen_crisis_blocked(client):
    resp = client.post("/dispatch", json={"agent": "report_gen", "payload": {"theme": "我不想活了"}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "blocked"
    assert body["human_review_required"] is True


def test_report_gen_returns_new_contract(client, tmp_path, monkeypatch):
    run_dir = _fake_run(tmp_path)
    monkeypatch.setattr("app.main.run_gen_audit_from_path", lambda **kw: run_dir)
    resp = client.post("/dispatch", json={"agent": "report_gen",
                                          "payload": {"image_path": "/tmp/x.jpg", "theme": "自我成长"}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["report_id"] == run_dir.name
    assert body["report"] == "报告正文"
    assert body["audit"] == "合规通过"
    assert "linkage" in body["context"]


def test_dispatch_unknown_agent(client):
    resp = client.post("/dispatch", json={"agent": "nope", "payload": {}})
    assert resp.status_code == 422


def test_report_qa_missing_report_id(client):
    resp = client.post("/dispatch", json={"agent": "report_qa", "payload": {"user_question": "这是什么？"}})
    assert resp.status_code == 422


def test_report_qa_via_dispatch(client, monkeypatch):
    monkeypatch.setattr("app.main.answer_question", lambda **kw: {"answer": "ok", "sources": []})
    resp = client.post("/dispatch", json={"agent": "report_qa",
                                          "payload": {"report_id": "R-x", "user_question": "这是什么？"}})
    assert resp.status_code == 200
    assert resp.json()["answer"] == "ok"
