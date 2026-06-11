from __future__ import annotations
from pydantic import BaseModel


class ProdOutput(BaseModel):
    production_deployment_disabled: bool = True
    required_approvals: list[str] = ["Engineering Manager", "Security Review", "Change Advisory Board"]
    release_readiness: str = "PENDING_HUMAN_APPROVAL"
    message: str = "Production release is gated. Awaiting mandatory human approvals before any deployment."
