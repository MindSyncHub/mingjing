"""共享安全护栏（纯规则，无 LLM）。

输入检测：危机信号 / 严重心理问题 / 医学 / 法律财务 / 恶意。
输出审核：诊断 / 承诺 / 绝对化 / 评判 / 重大决策引导。
规则口径以 wf-report-qa.md §2.4 两张表为准；本模块只做规则执行，不做软审。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class GuardResult:
    blocked: bool = False
    category: str | None = None
    message: str = ""
    case_risk: bool = False
    violations: list[str] = field(default_factory=list)
    rewritten: str | None = None


# ---- 输入检测 ----
_TRANSFER = re.compile(r"来访者|案主|个案|患者|客人|对方说|他说|她说")
_CRISIS = re.compile(r"自杀|自残|自伤|割腕|跳楼|烧炭|上吊|轻生|不想活|活着没意思|活着没意义|结束生命|想死|去死|活不下去")
_SEVERE_PSYCH = re.compile(r"重度抑郁|精神病|精神分裂|幻觉|幻听|妄想|躁狂|双相|人格分裂")
_MEDICAL = re.compile(r"诊断|确诊|处方|用药|吃药|停药|抑郁症|焦虑症|强迫症|创伤后应激|PTSD|癌症|肿瘤|什么病|是不是病|怎么治")
_LEGAL_FIN = re.compile(r"起诉|被告|判刑|官司|合同纠纷|债务|欠债|高利贷|贷款|投资|股票|基金|买保险|卖房|买房")
_MALICIOUS = re.compile(r"傻[逼屄比]|脑残|去死吧|滚蛋|辱骂|人身攻击")


def check_input(text: str) -> GuardResult:
    """Step A 输入安全检测。命中即拦截；疗愈师转述来访者危机原话时仅提示个案风险、不拦截。"""
    text = text or ""
    if _CRISIS.search(text):
        if _TRANSFER.search(text):
            return GuardResult(
                blocked=False, category="crisis", case_risk=True,
                message="检测到来访者危机原话，请疗愈师注意个案风险（REFERRAL-REDLINES 指针），本轮不做常规解读",
            )
        return GuardResult(
            blocked=True, category="crisis",
            message="检测到危机信号，请立即寻求专业帮助；AI 不提供危机干预，建议联系当地心理危机干预渠道或尽快就医",
        )
    if _SEVERE_PSYCH.search(text):
        return GuardResult(blocked=True, category="severe_psych", message="涉及严重心理问题，建议就医，不做解读")
    if _MEDICAL.search(text):
        return GuardResult(blocked=True, category="medical", message="涉及医学问题，建议咨询医生，不做解读")
    if _LEGAL_FIN.search(text):
        return GuardResult(blocked=True, category="legal_financial", message="涉及法律/财务问题，建议咨询专业人士")
    if _MALICIOUS.search(text):
        return GuardResult(blocked=True, category="malicious", message="抱歉，这类问题无法回答")
    return GuardResult(blocked=False)


# ---- 输出审核 ----
_PROMISE = re.compile(r"一定|肯定|绝对|必然|百分之百|100%|保证")
_ABSOLUTE = re.compile(r"所有|永远|总是|从不|完全|毫无|必须")
_JUDGMENT = re.compile(r"你不应该|你应该|你不对|你错了|你怎么能|你不该")
_DIAGNOSIS = re.compile(
    r"你有[^，。；\n]{0,10}(抑郁症|焦虑症|强迫症|精神病|躁狂|双相|创伤后应激|PTSD)"
    r"|你是[^，。；\n]{0,10}(抑郁症|焦虑症|强迫症|精神病)"
    r"|(?:得了|确诊)[^，。；\n]{0,10}(抑郁症|焦虑症|癌症|肿瘤)"
)
_DECISION = re.compile(
    r"(?:你应该|建议你|赶紧)[^，。；\n]{0,8}(分手|离婚|辞职|离职)"
    r"|(?:跟他|和她|跟对方)(?:分手|离婚)"
)

_SOFTEN = {
    "一定": "可能", "肯定": "可能", "绝对": "可能", "必然": "可能",
    "百分之百": "可能", "100%": "可能", "保证": "建议",
    "所有": "大多数", "永远": "往往", "总是": "常常", "从不": "很少",
    "完全": "较", "毫无": "较少", "必须": "建议",
}


def audit_output(text: str, safety_level: str = "L1") -> GuardResult:
    """Step D 输出安全审核。命中即尽力改写为可能性/接纳性表达；返回 violations 与 rewritten。"""
    del safety_level  # L1/L2 规则当前一致；口径提醒在组装层（Step E）按场景附加
    text = text or ""
    violations: list[str] = []
    rewritten = text
    if _DIAGNOSIS.search(rewritten):
        violations.append("diagnosis")
        rewritten = _DIAGNOSIS.sub("可能存在情绪或心理层面的困扰（不是诊断），建议寻求专业评估", rewritten)
    if _DECISION.search(rewritten):
        violations.append("decision_guidance")
        rewritten = _DECISION.sub("请结合自身情况谨慎权衡，不替你作决定", rewritten)
    if _PROMISE.search(rewritten):
        violations.append("promise")
        rewritten = _PROMISE.sub(lambda m: _SOFTEN.get(m.group(0), "可能"), rewritten)
    if _ABSOLUTE.search(rewritten):
        violations.append("absolutize")
        rewritten = _ABSOLUTE.sub(lambda m: _SOFTEN.get(m.group(0), "可能"), rewritten)
    if _JUDGMENT.search(rewritten):
        violations.append("judgment")
        rewritten = _JUDGMENT.sub("或许可以考虑", rewritten)
    if violations:
        return GuardResult(blocked=True, violations=violations, rewritten=rewritten)
    return GuardResult(blocked=False)
