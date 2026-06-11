from __future__ import annotations
from pydantic import BaseModel


class DevOpsOutput(BaseModel):
    deployment_readiness_checklist: list[str] = []
    infra_impact: str = "No infra changes required for this release."
    rollback_plan: str = "Revert to previous tag via git revert."
    production_deployment_disabled: bool = True
    message: str = "Production deployment is disabled. Human operator approval required to proceed."
