"""Request lifecycle tracing and elapsed-time observations."""

import time
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .correlation import correlation_id


def mark_trace(request: HttpRequest, event: str) -> None:
    events = getattr(request, "lab_trace", None)
    if events is not None:
        events.append(event)


class RequestTraceMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.correlation_id = correlation_id(request.headers.get("X-Correlation-ID", ""))
        request.lab_trace = ["trace.enter"]
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        mark_trace(request, "trace.exit")
        response.headers["X-Correlation-ID"] = request.correlation_id
        response.headers["X-Lab-Trace"] = ">".join(request.lab_trace[:16])
        response.headers["X-Request-Duration-Ms"] = f"{elapsed_ms:.3f}"
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.3f}"
        return response
