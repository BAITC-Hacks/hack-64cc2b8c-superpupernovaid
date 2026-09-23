from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from app.notifications.models import ReminderPage
from app.notifications.service import ReminderService, get_reminders

router = APIRouter(prefix="/api/v1/notifications", tags=["Reminders"])
Service = Annotated[ReminderService, Depends(get_reminders)]


@router.get("", response_model=ReminderPage)
def list_reminders(
    service: Service,
    meeting_id: UUID | None = None,
    status: Literal["pending", "read", "cancelled"] = "pending",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    try:
        return {"items": service.list(meeting_id, status, limit, offset)}
    except SQLAlchemyError:
        raise HTTPException(503, "Reminders unavailable") from None


@router.post("/scan")
def scan_reminders(service: Service):
    try:
        return service.scan()
    except SQLAlchemyError:
        raise HTTPException(503, "Reminders unavailable") from None


@router.post("/{notification_id}/read")
def read_reminder(notification_id: UUID, service: Service):
    try:
        return service.mark_read(notification_id)
    except SQLAlchemyError:
        raise HTTPException(503, "Reminders unavailable") from None
