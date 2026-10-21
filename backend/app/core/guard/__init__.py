"""共享安全护栏（core/guard）。"""

from .rules import GuardResult, audit_output, check_input

__all__ = ["GuardResult", "audit_output", "check_input"]
