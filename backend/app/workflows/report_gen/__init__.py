"""报告生成：gen-audit 架构（自由生成 + 合规/超纲校验，D-013）。"""

from .gen_audit import GenAuditError, run_gen_audit, run_gen_audit_from_path

__all__ = ["GenAuditError", "run_gen_audit", "run_gen_audit_from_path"]
