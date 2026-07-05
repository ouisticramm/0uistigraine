from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Dict

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from .database import PriceMarket, Material
from . import alert_engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def get_current_prices(session: AsyncSession) -> Dict[str, float]:
    # latest row per material_code
    subq = (
        select(PriceMarket.material_code, func.max(PriceMarket.fetched_at).label("mx"))
        .group_by(PriceMarket.material_code)
        .subquery()
    )
    q = (
        select(PriceMarket.material_code, PriceMarket.price_per_tonne)
        .join(subq, (PriceMarket.material_code == subq.c.material_code) & (PriceMarket.fetched_at == subq.c.mx))
    )
    rows = (await session.execute(q)).all()
    return {code: float(price) for code, price in rows}


async def _avg_last_n(session: AsyncSession, material_code: str, n: int = 30) -> float:
    q = (
        select(PriceMarket.price_per_tonne)
        .where(PriceMarket.material_code == material_code)
        .order_by(PriceMarket.fetched_at.desc())
        .limit(n)
    )
    rows = (await session.execute(q)).scalars().all()
    if not rows:
        return 0.0
    return float(sum(rows) / len(rows))


async def drift_prices(session: AsyncSession) -> Dict[str, float]:
    # ensure materials exist
    mats = (await session.execute(select(Material.code))).scalars().all()
    current = await get_current_prices(session)

    updated: Dict[str, float] = {}
    for code in mats:
        base = float(current.get(code, 0.0))
        if base <= 0:
            # keep 0 for NONREC etc
            updated[code] = base
            pm = PriceMarket(
                material_code=code,
                price_per_tonne=base,
                currency="EUR",
                source="SIMULATED",
                fetched_at=utcnow(),
                variation_pct=0.0,
            )
            session.add(pm)
            continue

        new_price = base * (1 + random.uniform(-0.02, 0.02))
        avg30 = await _avg_last_n(session, code, 30)
        variation_pct = 0.0
        if avg30 > 0:
            variation_pct = ((new_price - avg30) / avg30) * 100.0

        pm = PriceMarket(
            material_code=code,
            price_per_tonne=float(new_price),
            currency="EUR",
            source="SIMULATED",
            fetched_at=utcnow(),
            variation_pct=float(variation_pct),
        )
        session.add(pm)
        updated[code] = float(new_price)

        if variation_pct > 5.0:
            await alert_engine.create_alert(
                session=session,
                type="sale_opportunity",
                severity="low",
                message=f"Cours {code} +{variation_pct:.1f}% vs moyenne 30j.",
                context_data=f'{{"material":"{code}","variation_pct":{variation_pct:.2f}}}',
                detection_id=None,
                conveyor_id=3,
            )

    await session.commit()
    return updated


async def compute_stock_value(session: AsyncSession, totals_by_material_tonnes: Dict[str, float]) -> float:
    prices = await get_current_prices(session)
    total = 0.0
    for code, tonnes in totals_by_material_tonnes.items():
        if code in ("NONREC",):
            continue
        total += float(tonnes) * float(prices.get(code, 0.0))
    return float(total)
