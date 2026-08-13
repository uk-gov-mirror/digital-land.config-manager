"""Persistent status tracking for Assign Entities resources."""

from datetime import datetime

from application.db.models import AssignEntityResource
from application.extensions import db

IN_PROGRESS = "in_progress"
PROCESSED = "processed"


def set_assign_entity_resource_status(
    resource: str, status: str | None, actor_username: str
):
    """Create or update the current processing status for ``resource``."""
    record = db.session.get(AssignEntityResource, resource)
    if record is None:
        record = AssignEntityResource(resource=resource)
        db.session.add(record)

    record.status = status
    record.actor_username = actor_username
    record.updated_at = datetime.utcnow()
    db.session.commit()
    return record


def get_assign_entity_resource_statuses(resources: list[str]) -> dict[str, AssignEntityResource]:
    """Return persisted status records keyed by resource."""
    if not resources:
        return {}
    records = AssignEntityResource.query.filter(
        AssignEntityResource.resource.in_(resources)
    ).all()
    return {record.resource: record for record in records}
