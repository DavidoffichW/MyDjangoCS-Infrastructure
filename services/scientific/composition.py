"""Runtime composition of the stable foundation with local preservation."""

from pathlib import Path

from django.conf import settings

from foundation import FoundationAPI
from infrastructure.preservation import ContentAddressedStore


def foundation_api() -> FoundationAPI:
    return FoundationAPI(ContentAddressedStore(Path(settings.ARTIFACT_STORE_ROOT)))
