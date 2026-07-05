from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, List, Any, Dict

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Alert, Bale, Detection


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_alert(
    session: AsyncSession,
    type: str,
    severity: str,
    message: str,
    context_data: str,
    detection_id: Optional[str] = None,
    conveyor_id: Optional[int] = None,
) -> Alert:
    a = Alert(
        type=type,
        severity=severity,
        message=message,
        context_data=context_data,
        acknowledged=False,
        triggered_at=utcnow(),
        detection_id=detection_id,
        conveyor_id=conveyor_id,
    )
    session.add(a)
    await session.commit()
    return a


async def get_active_alerts(session: AsyncSession, conveyor_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    q = (
        select(Alert)
        .where(and_(Alert.acknowledged == False, Alert.conveyor_id == conveyor_id))  # noqa: E712
        .order_by(Alert.triggered_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(q)).scalars().all()
    # front expects list of dicts (we keep current front structure: id/type/severity/message/ts)
    out: List[Dict[str, Any]] = []
    for a in rows:
        icon = "!" if a.severity == "high" else "↘" if a.severity == "medium" else "€"
        out.append(
            {
                "id": str(a.id),
                "type": "high" if a.severity == "high" else "medium" if a.severity == "medium" else "sale",
                "icon": icon,
                "title": a.type,
                "message": a.message,
                "ts": int(a.triggered_at.timestamp() * 1000),
            }
        )
    return out


async def evaluate_detection(session: AsyncSession, detection: Detection) -> None:
    # V1 simplification: expected flow on conveyor 3 is PET
    expected = "PET"

    if detection.conveyor_id == 3 and detection.material_type in ("ALU", "ACIER") and detection.material_type != expected:
        await create_alert(
            session=session,
            type="sort_error",
            severity="high",
            message=f"{detection.material_type} détecté dans flux PET (caméra {detection.camera_id}).",
            context_data=f'{{"material":"{detection.material_type}","camera_id":{detection.camera_id}}}',
            detection_id=detection.id,
            conveyor_id=detection.conveyor_id,
        )

    # pickup_ready: bale >= 95% target, only once per bale
    q_bale = (
        select(Bale)
        .where(Bale.conveyor_id == detection.conveyor_id, Bale.status == "in_progress")
        .order_by(Bale.started_at.desc())
        .limit(1)
    )
    bale = (await session.execute(q_bale)).scalars().first()
    if not bale:
        return

    if bale.current_weight_kg >= bale.target_weight_kg * 0.95:
        # check if already alerted for this bale reference
        q_existing = select(func.count()).select_from(Alert).where(
            Alert.type == "pickup_ready",
            Alert.conveyor_id == bale.conveyor_id,
            Alert.message.like(f"%{bale.reference}%"),
        )
        n = await session.scalar(q_existing)
        if not n:
            await create_alert(
                session=session,
                type="pickup_ready",
                severity="low",
                message=f"Balle {bale.reference} bientôt complète (≥95%).",
                context_data=f'{{"bale_reference":"{bale.reference}","progress_pct":{(bale.current_weight_kg/bale.target_weight_kg*100):.1f}}}',
                detection_id=None,
                conveyor_id=bale.conveyor_id,
            )


async def evaluate_quality(session: AsyncSession, conveyor_id: int) -> None:
    # V1: use current bale purity as proxy (no multi-bales computation)
    q = (
        select(Bale.purity_pct)
        .where(Bale.conveyor_id == conveyor_id, Bale.status == "in_progress")
        .order_by(Bale.started_at.desc())
        .limit(1)
    )
    purity = (await session.execute(q)).scalars().first()
    if purity is None:
        return

    if float(purity) < 90.0:
        await create_alert(
            session=session,
            type="quality_drop",
            severity="medium",
            message=f"Pureté passée sous 90% (actuel {float(purity):.1f}%).",
            context_data=f'{{"purity_pct":{float(purity):.1f}}}',
            detection_id=None,
            conveyor_id=conveyor_id,
        )
