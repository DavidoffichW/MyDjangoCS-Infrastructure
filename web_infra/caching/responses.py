"""Private cached HTML representations for immutable successful results."""

from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string

from workflows.models import Job

from .identities import result_representation_key


def cached_result_response(request: HttpRequest, job: Job) -> HttpResponse:
    variant = "fragment" if request.htmx else "page"
    key = result_representation_key(job, variant)
    content = cache.get(key)
    cache_status = "HIT"
    if content is None:
        template = "workflows/partials/result.html" if request.htmx else "workflows/result.html"
        content = render_to_string(template, {"job": job}, request=request)
        cache.set(key, content, timeout=300)
        cache_status = "MISS"
    response = HttpResponse(content)
    response.headers["X-Lab-Cache"] = cache_status
    response.headers["Cache-Control"] = "private, max-age=60"
    return response
