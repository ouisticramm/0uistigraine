from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .database import AsyncSessionLocal, init_db, Material, Conveyor, PriceMarket
from .ws_manager import WSManager
from . import kpi_engine, simulator, alert_engine, price_engine

from sqlalchemy import select, func


app = FastAPI(title="TrashData API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ws_manager = WSManager()
scheduler: Optional[AsyncIOScheduler] = None


@app.on_event("startup")
async def startup() -> None:
    global scheduler
    await init_db()

    # start simulator loop (detections every 300ms)
    asyncio.create_task(simulation_loop())
    asyncio.create_task(safety_ticker_loop())

    # quality check loop every 60s
    asyncio.create_task(quality_check_loop())

    # price drift via APScheduler (every 15 min)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(price_drift_job, "interval", seconds=60)
    scheduler.start()


async def price_drift_job() -> None:
    async with AsyncSessionLocal() as session:
        await price_engine.drift_prices(session)


async def simulation_loop() -> None:
    # broadcast on every detection + safety tick every 5s handled below
    while True:
        async with AsyncSessionLocal() as session:
            det = await simulator.generate_detection(session)
            await simulator.upsert_brand_stat(session, det)
            await simulator.update_bale(session, det)
            await alert_engine.evaluate_detection(session, det)
            snap = await kpi_engine.compute_snapshot(session, conveyor_id=3)
        await ws_manager.broadcast({"type": "kpi_snapshot", "data": snap})
        await asyncio.sleep(0.3)


async def quality_check_loop() -> None:
    while True:
        await asyncio.sleep(60)
        async with AsyncSessionLocal() as session:
            await alert_engine.evaluate_quality(session, conveyor_id=3)


async def safety_ticker_loop() -> None:
    while True:
        await asyncio.sleep(5)
        async with AsyncSessionLocal() as session:
            snap = await kpi_engine.compute_snapshot(session, conveyor_id=3)
        await ws_manager.broadcast({"type": "kpi_snapshot", "data": snap})


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok"}


@app.get("/materials")
async def get_materials() -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Material))).scalars().all()
        return [{"code": m.code, "label_fr": m.label_fr} for m in rows]


@app.get("/conveyors")
async def get_conveyors() -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Conveyor))).scalars().all()
        return [{"id": c.id, "name": c.name, "location": c.location, "speed_ms": c.speed_ms, "status": c.status} for c in rows]


@app.get("/prices/latest")
async def get_prices_latest() -> Dict[str, Any]:
    async with AsyncSessionLocal() as session:
        prices = await price_engine.get_current_prices(session)
        drift = await kpi_engine._latest_price_variations(session)
        return {"currency": "EUR", "source": "SIMULATED", "prices": prices, "priceDrift": drift}


@app.get("/alerts")
async def get_alerts(conveyor_id: int = 3, limit: int = 20) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        return await alert_engine.get_active_alerts(session, conveyor_id=conveyor_id, limit=limit)



@app.get("/detections")
async def get_detections(conveyor_id: int = 3, limit: int = 50) -> List[Dict[str, Any]]:
    """Last N detections for debugging."""
    from .database import Detection
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Detection)
            .where(Detection.conveyor_id == conveyor_id)
            .order_by(Detection.detected_at.desc())
            .limit(limit)
        )).scalars().all()
        return [
            {
                "id": d.id,
                "detected_at": d.detected_at.isoformat(),
                "material_type": d.material_type,
                "brand_name": d.brand_name,
                "weight_kg": float(d.weight_kg),
                "confidence_score": float(d.confidence_score),
                "camera_id": d.camera_id,
            }
            for d in rows
        ]

@app.websocket("/ws/live")
async def ws_live(ws: WebSocket, conveyor_id: int = 3):
    await ws_manager.connect(ws)

    # send initial snapshot immediately
    async with AsyncSessionLocal() as session:
        snap = await kpi_engine.compute_snapshot(session, conveyor_id=conveyor_id)
    await ws.send_json({"type": "kpi_snapshot", "data": snap})

    try:
        # keepalive (client doesn't send anything in our case)
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(ws)
