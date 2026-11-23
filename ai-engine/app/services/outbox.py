import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.integrations.frappe_client import FrappeClient
from app.models.outbox import TutorOutboxEvent

logger = logging.getLogger(__name__)
frappe_client = FrappeClient()


async def deliver_one(db: Session, item: TutorOutboxEvent) -> bool:
    try:
        if item.kind == "session_snapshot":
            await frappe_client.save_tutor_session(item.payload)
        elif item.kind == "progress_event":
            await frappe_client.save_event(item.payload)
        else:
            logger.error("Unknown LMS outbox event kind: %s", item.kind)
            return False
    except Exception:
        item.attempts += 1
        delay_seconds = min(900, 5 * (2 ** min(item.attempts - 1, 8)))
        item.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        db.commit()
        logger.warning("LMS synchronization deferred; outbox id=%s attempts=%s", item.id, item.attempts)
        return False

    item.delivered_at = datetime.now(timezone.utc)
    db.commit()
    return True


async def deliver_items(db: Session, items: list[TutorOutboxEvent]) -> bool:
    delivered = True
    for item in items:
        delivered = await deliver_one(db, item) and delivered
    return delivered


async def process_pending_batch(batch_size: int = 20) -> int:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        items = list(
            db.scalars(
                select(TutorOutboxEvent)
                .where(
                    TutorOutboxEvent.delivered_at.is_(None),
                    TutorOutboxEvent.next_attempt_at <= now,
                )
                .order_by(TutorOutboxEvent.created_at)
                .limit(batch_size)
            )
        )
        for item in items:
            await deliver_one(db, item)
        retention_cutoff = now - timedelta(days=30)
        db.execute(
            delete(TutorOutboxEvent).where(
                TutorOutboxEvent.delivered_at.is_not(None),
                TutorOutboxEvent.delivered_at < retention_cutoff,
            )
        )
        db.commit()
        return len(items)
    finally:
        db.close()


async def run_outbox_worker() -> None:
    while True:
        try:
            await process_pending_batch()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("LMS outbox worker encountered an unexpected error")
        await asyncio.sleep(5)
