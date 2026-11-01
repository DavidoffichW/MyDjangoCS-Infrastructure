"""Reconcile durable artifact metadata with immutable stored bytes."""

from django.utils import timezone

from foundation.contracts.errors import ArtifactError


def reconcile_artifact_records(
    records, store, reference_factory, *, quarantine_orphans: bool = False
):
    registered = {record.identity: record for record in records.all()}
    registered_digests = {identity.rsplit(":", 1)[-1] for identity in registered}
    store_digests = set(store.iter_digests())
    report = {"corrupt": [], "missing": [], "orphans": [], "verified": []}
    for identity, record in registered.items():
        reference = reference_factory(record)
        try:
            store.verify(reference)
        except ArtifactError:
            record.state = (
                record.State.CORRUPT if store.path_for(reference).exists() else record.State.MISSING
            )
            record.verified_at = timezone.now()
            record.save(update_fields=["state", "verified_at"])
            report[record.state].append(identity)
        else:
            record.state = record.State.REGISTERED
            record.verified_at = timezone.now()
            record.save(update_fields=["state", "verified_at"])
            report["verified"].append(identity)
    for digest in sorted(store_digests - registered_digests):
        report["orphans"].append(digest)
        if quarantine_orphans:
            store.quarantine_digest(digest)
    return report
