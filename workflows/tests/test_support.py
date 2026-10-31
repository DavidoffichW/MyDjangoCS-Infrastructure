from django.http import HttpResponse

from reliability_lab.middleware import mark_trace


def echo_view(request):
    mark_trace(request, "view.echo")
    return HttpResponse("ok")


def exception_view(request):
    mark_trace(request, "view.raise")
    raise RuntimeError("deliberate view failure")


class RaisingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        mark_trace(request, "middleware.raise")
        raise RuntimeError("deliberate middleware failure")
