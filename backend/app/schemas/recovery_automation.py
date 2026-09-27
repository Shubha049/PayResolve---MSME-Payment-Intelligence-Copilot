from pydantic import BaseModel


class RecoveryAutomationRunResult(BaseModel):
    created_count: int
    promise_overdue: int
    follow_up_due: int
    broken_promise_attention: int
