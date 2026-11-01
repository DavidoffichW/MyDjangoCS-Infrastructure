"""Stable JSON error envelope."""

from django.http import JsonResponse

API_VERSION = "mydjangocs.http-api/1"


def api_error(code: str, message: str, status: int) -> JsonResponse:
    return JsonResponse(
        {"api_version": API_VERSION, "error": {"code": code, "message": message}, "ok": False},
        status=status,
    )
