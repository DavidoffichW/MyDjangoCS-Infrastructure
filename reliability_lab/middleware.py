from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

_CORRELATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


def mark_trace(request: HttpRequest, event: str) -> None:
    events = getattr(request, "lab_trace", None)
    if events is not None:
        events.append(event)


class RequestTraceMiddleware:
    """Attach a bounded request trace and timing observations to each response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        supplied = request.headers.get("X-Correlation-ID", "")
        correlation_id = supplied if _CORRELATION_ID.fullmatch(supplied) else uuid.uuid4().hex
        request.correlation_id = correlation_id
        request.lab_trace = ["trace.enter"]
        started = time.perf_counter()

        response = self.get_response(request)

        elapsed_ms = (time.perf_counter() - started) * 1000
        mark_trace(request, "trace.exit")
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Lab-Trace"] = ">".join(request.lab_trace[:16])
        response.headers["X-Request-Duration-Ms"] = f"{elapsed_ms:.3f}"
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.3f}"
        return response


class DemonstrationGuardMiddleware:
    """A testable short-circuit that deliberately contains no domain logic."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.headers.get("X-Lab-Short-Circuit") == "1":
            mark_trace(request, "guard.block")
            return HttpResponse("Request stopped by the lab guard.", status=429)
        mark_trace(request, "guard.pass")
        return self.get_response(request)
