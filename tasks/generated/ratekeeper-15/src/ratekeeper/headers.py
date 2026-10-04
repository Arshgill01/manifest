"""HTTP response headers for rate-limit decisions."""

from __future__ import annotations

import math

from .limiter import Decision
from .quota import get_plan


def rate_limit_headers(decision: Decision, plan_name: str) -> dict[str, str]:
    plan = get_plan(plan_name)
    headers = {
        "X-RateLimit-Limit": str(plan.burst),
        "X-RateLimit-Remaining-Day": str(decision.remaining_today),
    }
    if not decision.allowed:
        headers["Retry-After"] = str(max(1, math.ceil(decision.retry_after)))
    return headers
