from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone, date
from typing import Optional, Tuple, Dict, List
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Detection, BrandStat, Bale


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


MATERIAL_WEIGHTS: Dict[str, Tuple[float, float]] = {
    "PET": (0.025, 0.080),
    "PEHD": (0.050, 0.150),
    "ALU": (0.015, 0.045),
    "ACIER": (0.080, 0.250),
    "CARTON": (0.200, 0.800),
    "NONREC": (0.050, 0.300),
    "ENERGIE": (0.100, 0.500),
}

MATERIAL_DISTRIBUTION = [
    ("PET", 0.25),
    ("CARTON", 0.22),
    ("PEHD", 0.15),
    ("ENERGIE", 0.14),
    ("NONREC", 0.12),
    ("ALU", 0.08),
    ("ACIER", 0.04),
]

BRANDS: Dict[str, List[Optional[str]]] = {
    "PET": ["Evian", "Volvic", "Cristaline", "Perrier", "Badoit", "AquaPure"],
    "ALU": ["Coca-Cola", "Red Bull", "Heineken", "Kronenbourg", "Orangina"],
    "CARTON": ["FreshBox", "Lactel", "Danette", "Carrefour", "Nestle"],
    "PEHD": ["DailyCare", "Ariel", "Le Chat", "Skip", "Mir"],
    "ACIER": ["Bonduelle", "Cassegrain", "William Saurin", "Raynal"],
    "NONREC": [None],
    "ENERGIE": [None],
}

COLORS = {"PET": "clear", "PEHD": "white", "ALU": "silver", "ACIER": "grey", "CARTON": "brown", "NONREC": "mixed", "ENERGIE": "mixed"}
STATES = ["crushed", "intact", "damaged"]
ERROR_RATE = 0.04


def weighted_random(dist) -> str:
    mats = [m for m, _ in dist]
    w = [p for _, p in dist]
    return random.choices(mats, weights=w, k=1)[0]


async def generate_detection(session: AsyncSession) -> Detection:
    if random.random() < ERROR_RATE:
        material = random.choice(["ALU", "ACIER", "NONREC"])
    else:
        material = weighted_random(MATERIAL_DISTRIBUTION)

    weight_kg = random.uniform(*MATERIAL_WEIGHTS[material])
    brand_list = BRANDS.get(material, [None])
    brand = random.choice(brand_list) if brand_list and brand_list[0] is not None else None

    det = Detection(
        id=str(uuid4()),
        detected_at=utcnow(),
        material_type=material,
        brand_name=brand,
        confidence_score=round(random.uniform(0.85, 0.99), 3),
        weight_kg=round(weight_kg, 4),
        color=COLORS[material],
        state=random.choice(STATES),
        bounding_box=json.dumps(
            {
                "x": round(random.uniform(0, 0.8), 2),
                "y": round(random.uniform(0, 0.8), 2),
                "w": round(random.uniform(0.05, 0.25), 2),
                "h": round(random.uniform(0.05, 0.2), 2),
            }
        ),
        camera_id=random.choice([1, 2, 3]),
        conveyor_id=3,
        bale_id=1 if material == "PET" else None,
    )
    session.add(det)
    await session.commit()
    return det


async def upsert_brand_stat(session: AsyncSession, detection: Detection) -> None:
    if not detection.brand_name:
        return
    today = date.today()
    q = select(BrandStat).where(
        BrandStat.brand_name == detection.brand_name,
        BrandStat.stat_date == today,
        BrandStat.conveyor_id == detection.conveyor_id,
    )
    row = (await session.execute(q)).scalars().first()
    if row:
        row.count_units += 1
        row.weight_total_kg += float(detection.weight_kg)
        # simplistic dominant material = last seen
        row.material_dominant = detection.material_type
    else:
        session.add(
            BrandStat(
                brand_name=detection.brand_name,
                material_dominant=detection.material_type,
                count_units=1,
                weight_total_kg=float(detection.weight_kg),
                refusal_rate_pct=0.0,
                stat_date=today,
                conveyor_id=detection.conveyor_id,
            )
        )
    await session.commit()


async def update_bale(session: AsyncSession, detection: Detection) -> None:
    if detection.material_type != "PET":
        return
    q = select(Bale).where(Bale.id == 1, Bale.status == "in_progress")
    bale = (await session.execute(q)).scalars().first()
    if not bale:
        return
    bale.current_weight_kg += float(detection.weight_kg)
    await session.commit()
