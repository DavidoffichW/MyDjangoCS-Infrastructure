"""Demonstration-only middleware short circuit with no domain logic."""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .tracing import mark_trace


class DemonstrationGuardMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.headers.get("X-Lab-Short-Circuit") == "1":
            mark_trace(request, "guard.block")
            return HttpResponse("Request stopped by the lab guard.", status=429)
        mark_trace(request, "guard.pass")
        return self.get_response(request)
