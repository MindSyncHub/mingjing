def test_input_prep_upload(client, tmp_path, monkeypatch):
    """管线最小验收：上传照片 → 存盘 → 返回确认（specs/input-prep.md 1.2 输入契约）。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import Settings

    import app.main as main_module

    main_module.settings = Settings()
    payload = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes"  # JPEG 魔数开头
    resp = client.post(
        "/input-prep",
        files={"photo": ("test.jpg", payload, "image/jpeg")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] == "test.jpg"
    assert body["bytes"] == len(payload)
