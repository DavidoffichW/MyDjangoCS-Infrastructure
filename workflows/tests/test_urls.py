from django.urls import path

from .test_support import echo_view, exception_view

urlpatterns = [
    path("echo/", echo_view, name="test-echo"),
    path("exception/", exception_view, name="test-exception"),
]
