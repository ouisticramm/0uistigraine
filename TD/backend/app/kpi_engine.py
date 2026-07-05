from __future__ import annotations

from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy import select, func, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Detection, Bale, BrandStat, PriceMarket
from . import price_engine, alert_engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _latest_price_variations(session: AsyncSession) -> Dict[str, float]:
    subq = (
        select(PriceMarket.material_code, func.max(PriceMarket.fetched_at).label("mx"))
        .group_by(PriceMarket.material_code)
        .subquery()
    )
    q = (
        select(PriceMarket.material_code, PriceMarket.variation_pct)
        .join(subq, (PriceMarket.material_code == subq.c.material_code) & (PriceMarket.fetched_at == subq.c.mx))
    )
    rows = (await session.execute(q)).all()
    return {code: float(v) / 100.0 for code, v in rows}  # front expects drift ratio (0.05), not percent (5)


async def compute_snapshot(session: AsyncSession, conveyor_id: int = 3) -> Dict[str, Any]:
    today = date.today()
    start_day = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    one_hour_ago = utcnow() - timedelta(hours=1)

    # detections today
    q_total_weight = select(func.coalesce(func.sum(Detection.weight_kg), 0.0)).where(
        Detection.conveyor_id == conveyor_id,
        Detection.detected_at >= start_day,
    )
    total_weight_kg = float(await session.scalar(q_total_weight) or 0.0)

    q_hour_weight = select(func.coalesce(func.sum(Detection.weight_kg), 0.0)).where(
        Detection.conveyor_id == conveyor_id,
        Detection.detected_at >= one_hour_ago,
    )
    hour_weight_kg = float(await session.scalar(q_hour_weight) or 0.0)

    q_count = select(func.count()).select_from(Detection).where(
        Detection.conveyor_id == conveyor_id,
        Detection.detected_at >= start_day,
    )
    detections_count = int(await session.scalar(q_count) or 0)

    # tonnage_by_material (tonnes)
    q_by_mat = (
        select(Detection.material_type, func.coalesce(func.sum(Detection.weight_kg), 0.0))
        .where(Detection.conveyor_id == conveyor_id, Detection.detected_at >= start_day)
        .group_by(Detection.material_type)
    )
    rows = (await session.execute(q_by_mat)).all()
    tonnage_by_material = {mat: float(wkg) / 1000.0 for mat, wkg in rows}

    # prices and drift
    prices = await price_engine.get_current_prices(session)
    price_drift = await _latest_price_variations(session)  # ratio

    # value_by_material
    value_by_material: Dict[str, float] = {}
    for mat, tonnes in tonnage_by_material.items():
        value_by_material[mat] = float(tonnes) * float(prices.get(mat, 0.0))

    total_value_eur = float(sum(value_by_material.values()))

    # error rate (V1)
    if detections_count > 0:
        q_err = select(func.count()).select_from(Detection).where(
            Detection.conveyor_id == conveyor_id,
            Detection.detected_at >= start_day,
            Detection.material_type.in_(["ALU", "ACIER", "NONREC"]),
        )
        err_count = int(await session.scalar(q_err) or 0)
        error_rate_pct = (err_count / detections_count) * 100.0
    else:
        error_rate_pct = 0.0

    # purity from active bale
    q_purity = select(Bale).where(Bale.conveyor_id == conveyor_id, Bale.status == "in_progress").order_by(Bale.started_at.desc()).limit(1)
    bale = (await session.execute(q_purity)).scalars().first()
    purity_pct = float(bale.purity_pct) if bale else 0.0

    # top brands from brand_stat today
    q_top = (
        select(BrandStat.brand_name, BrandStat.count_units, BrandStat.material_dominant)
        .where(BrandStat.conveyor_id == conveyor_id, BrandStat.stat_date == today)
        .order_by(BrandStat.count_units.desc())
        .limit(5)
    )
    top_rows = (await session.execute(q_top)).all()
    top_brands = [{"name": b, "count": int(c), "note": ""} for (b, c, m) in top_rows]

    # history: per hour since 06:00 (tonnage/heure → débit front expects)
    start_6 = datetime(today.year, today.month, today.day, 6, 0, 0, tzinfo=timezone.utc)
    q_hist = (
        select(func.strftime("%H", Detection.detected_at).label("hour"), func.coalesce(func.sum(Detection.weight_kg), 0.0))
        .where(Detection.conveyor_id == conveyor_id, Detection.detected_at >= start_6)
        .group_by(text("hour"))
        .order_by(text("hour"))
    )
    hist_rows = (await session.execute(q_hist)).all()
    # front expects: t (index) + throughput (tonnes/h, normalized to 0-26 scale)
    history = [{"t": i, "throughput": float(max(8.0, min(26.0, float(wkg) / 1000.0 * 2.0)))} for i, (h, wkg) in enumerate(hist_rows)]

    # alerts (front shape)
    alerts = await alert_engine.get_active_alerts(session, conveyor_id=conveyor_id, limit=6)

    # loss_total_eur proxy: refus valorisables = 7% total_value
    loss_total_eur = total_value_eur * 0.07

    # score
    quality_score = round(purity_pct)
    performance_score = round(max(0.0, 100.0 - error_rate_pct * 10.0))
    valorization_score = round(min(100.0, (total_value_eur / 50000.0) * 100.0)) if total_value_eur > 0 else 0
    global_score = round(quality_score * 0.4 + performance_score * 0.3 + valorization_score * 0.3)

    # recommendation (simple: best variation_pct)
    best_mat = None
    best_var = -999.0
    for mat, drift_ratio in price_drift.items():
        var_pct = drift_ratio * 100.0
        if var_pct > best_var:
            best_var = var_pct
            best_mat = mat
    if best_mat and best_var > 5.0:
        rec = {
            "action": "sell_now",
            "material": best_mat,
            "reason": f"{best_mat} est +{best_var:.1f}% au-dessus de sa moyenne 30j",
            "value_eur": float(value_by_material.get(best_mat, 0.0)),
        }
    else:
        rec = {"action": "hold", "material": None, "reason": "Cours stables", "value_eur": 0.0}

    # opportunities (keep front expectations: label + value (number) + note)
    opportunities = [
        {"label": "Refus valorisables", "value": round(loss_total_eur), "note": "Récupérables dans les refus"},
        {"label": "Opportunité aluminium", "value": int(abs(prices.get("ALU", 0.0) - 1180.0) * (tonnage_by_material.get("ALU", 0.0) * 0.4)) if prices.get("ALU", 0.0) > 1180.0 else 1200, "note": "Cours favorable et stock disponible"},
        {"label": "Qualité PET", "value": 2000, "note": "Gain potentiel sur pureté PET clair"},
    ]
    opportunity_total = float(sum(float(o["value"]) for o in opportunities))

    bale_active = None
    bale_progress = 0.0
    if bale:
        prog = 0.0
        if bale.target_weight_kg > 0:
            prog = float(bale.current_weight_kg) / float(bale.target_weight_kg) * 100.0
        bale_progress = prog
        bale_active = {
            "reference": bale.reference,
            "material_type": bale.material_type,
            "current_weight_kg": float(bale.current_weight_kg),
            "target_weight_kg": float(bale.target_weight_kg),
            "purity_pct": float(bale.purity_pct),
            "progress_pct": float(prog),
        }

    # lastDetection: latest row
    q_last = select(Detection).where(Detection.conveyor_id == conveyor_id).order_by(Detection.detected_at.desc()).limit(1)
    last = (await session.execute(q_last)).scalars().first()
    last_detection = None
    if last:
        last_detection = {
            "material": last.material_type,
            "code": last.material_type,
            "weight": float(last.weight_kg),
            "brand": last.brand_name,
            "confidence": float(last.confidence_score) * 100.0,
            "ts": int(last.detected_at.timestamp() * 1000),
        }

    # IMPORTANT: keep the EXACT shape used by the current React dashboard
    return {
        "totalT": float(total_weight_kg) / 1000.0,
        "totalValue": float(total_value_eur),
        "valueByMaterial": value_by_material,
        "detectionsCount": detections_count,
        "errorRatePct": float(error_rate_pct),
        "purityPct": float(purity_pct),
        "prices": prices,
        "priceDrift": price_drift,
        "history": history,
        "alerts": alerts,
        "lastDetection": last_detection,
        "baleProgress": float(bale_progress),
        "score": {"global": int(global_score), "quality": int(quality_score), "performance": int(performance_score), "valorisation": int(valorization_score)},
        "topBrands": top_brands,
        "opportunities": opportunities,
        "opportunityTotal": opportunity_total,
        "tonnagePerHour": float(hour_weight_kg) / 1000.0,
    }
