from app.core.guard import audit_output, check_input


def test_input_crisis_blocks():
    r = check_input("我不想活了")
    assert r.blocked is True
    assert r.category == "crisis"


def test_input_transfer_crisis_is_case_risk_not_blocked():
    r = check_input("我的来访者说活着没意思")
    assert r.blocked is False
    assert r.case_risk is True
    assert r.category == "crisis"


def test_input_medical_blocks():
    r = check_input("我是不是有抑郁症")
    assert r.blocked is True
    assert r.category == "medical"


def test_input_legal_financial_blocks():
    r = check_input("我有债务纠纷怎么办")
    assert r.blocked is True
    assert r.category == "legal_financial"


def test_input_clean_passes():
    r = check_input("中间这圈的黄色代表什么？")
    assert r.blocked is False


def test_output_promise_softened():
    r = audit_output("你一定会好起来的")
    assert r.blocked is True
    assert "promise" in r.violations
    assert "一定" not in r.rewritten
    assert "可能" in r.rewritten


def test_output_diagnosis_rewritten():
    r = audit_output("你有抑郁症")
    assert r.blocked is True
    assert "diagnosis" in r.violations
    assert "不是诊断" in r.rewritten


def test_output_decision_guidance_neutralized():
    r = audit_output("你应该辞职")
    assert r.blocked is True
    assert "decision_guidance" in r.violations
    assert "辞职" not in r.rewritten


def test_output_judgment_softened():
    r = audit_output("你应该多运动")
    assert r.blocked is True
    assert "judgment" in r.violations
    assert "或许可以考虑" in r.rewritten


def test_output_clean_passes():
    r = audit_output("这份报告提到安全感不足，你可以结合自身情况看看。")
    assert r.blocked is False
    assert r.rewritten is None
