from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    String, Integer, Float, DateTime, Boolean, ForeignKey, Date, Text, UniqueConstraint
)
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import select, func


DB_URL = "sqlite+aiosqlite:///../trashdata.db"  # backend/trashdata.db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conveyor(Base):
    __tablename__ = "conveyor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    location: Mapped[str] = mapped_column(String(200))
    speed_ms: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))

    cameras: Mapped[List["Camera"]] = relationship(back_populates="conveyor")
    bales: Mapped[List["Bale"]] = relationship(back_populates="conveyor")


class Camera(Base):
    __tablename__ = "camera"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    serial_number: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    position: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    conveyor_id: Mapped[int] = mapped_column(ForeignKey("conveyor.id"))

    conveyor: Mapped["Conveyor"] = relationship(back_populates="cameras")


class Material(Base):
    __tablename__ = "material"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    label_fr: Mapped[str] = mapped_column(String(120))
    density: Mapped[float] = mapped_column(Float)
    recyclability: Mapped[str] = mapped_column(String(32))
    valorization_type: Mapped[str] = mapped_column(String(32))


class PriceMarket(Base):
    __tablename__ = "price_market"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_code: Mapped[str] = mapped_column(ForeignKey("material.code"), index=True)
    price_per_tonne: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    source: Mapped[str] = mapped_column(String(32), default="SIMULATED")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    variation_pct: Mapped[float] = mapped_column(Float, default=0.0)


class Bale(Base):
    __tablename__ = "bale"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(64))
    material_type: Mapped[str] = mapped_column(ForeignKey("material.code"), index=True)
    current_weight_kg: Mapped[float] = mapped_column(Float, default=0.0)
    target_weight_kg: Mapped[float] = mapped_column(Float, default=500.0)
    purity_pct: Mapped[float] = mapped_column(Float, default=94.0)
    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    conveyor_id: Mapped[int] = mapped_column(ForeignKey("conveyor.id"), index=True)

    conveyor: Mapped["Conveyor"] = relationship(back_populates="bales")


class Detection(Base):
    __tablename__ = "detection"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID string
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    material_type: Mapped[str] = mapped_column(ForeignKey("material.code"), index=True)
    brand_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    color: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32))
    bounding_box: Mapped[str] = mapped_column(Text)
    camera_id: Mapped[int] = mapped_column(ForeignKey("camera.id"), index=True)
    conveyor_id: Mapped[int] = mapped_column(ForeignKey("conveyor.id"), index=True)
    bale_id: Mapped[Optional[int]] = mapped_column(ForeignKey("bale.id"), nullable=True)


class Alert(Base):
    __tablename__ = "alert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(400))
    context_data: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    detection_id: Mapped[Optional[str]] = mapped_column(ForeignKey("detection.id"), nullable=True, index=True)
    conveyor_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)


class BrandStat(Base):
    __tablename__ = "brand_stat"
    __table_args__ = (
        UniqueConstraint("brand_name", "stat_date", "conveyor_id", name="uq_brand_stat_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_name: Mapped[str] = mapped_column(String(120))
    material_dominant: Mapped[str] = mapped_column(String(16))
    count_units: Mapped[int] = mapped_column(Integer, default=0)
    weight_total_kg: Mapped[float] = mapped_column(Float, default=0.0)
    refusal_rate_pct: Mapped[float] = mapped_column(Float, default=0.0)
    stat_date: Mapped[datetime.date] = mapped_column(Date)
    conveyor_id: Mapped[int] = mapped_column(ForeignKey("conveyor.id"), index=True)


engine = create_async_engine(DB_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # seed if material empty
        n = await session.scalar(select(func.count()).select_from(Material))
        if n and n > 0:
            return

        # Conveyors
        session.add_all([
            Conveyor(id=1, name="Ligne A1", location="Hall nord", speed_ms=1.2, status="active"),
            Conveyor(id=2, name="Ligne A2", location="Hall nord", speed_ms=1.4, status="active"),
            Conveyor(id=3, name="Ligne A3", location="Hall sud", speed_ms=1.3, status="active"),
        ])

        # Cameras (on conveyor 3)
        session.add_all([
            Camera(id=1, serial_number="BSL-2024-001", model="Basler acA1920", position="entrée", status="active", conveyor_id=3),
            Camera(id=2, serial_number="BSL-2024-002", model="Basler acA1920", position="milieu", status="active", conveyor_id=3),
            Camera(id=3, serial_number="FLIR-2024-001", model="FLIR A35 NIR", position="sortie", status="active", conveyor_id=3),
        ])

        # Materials
        session.add_all([
            Material(code="PET", label_fr="PET clair", density=1.38, recyclability="high", valorization_type="recyclage"),
            Material(code="PEHD", label_fr="PEHD", density=0.95, recyclability="high", valorization_type="recyclage"),
            Material(code="ALU", label_fr="Aluminium", density=2.70, recyclability="high", valorization_type="recyclage"),
            Material(code="ACIER", label_fr="Acier", density=7.85, recyclability="high", valorization_type="recyclage"),
            Material(code="CARTON", label_fr="Carton", density=0.70, recyclability="high", valorization_type="recyclage"),
            Material(code="NONREC", label_fr="Non recyclables", density=1.10, recyclability="none", valorization_type="enfouissement"),
            Material(code="ENERGIE", label_fr="Valorisables énergie", density=0.90, recyclability="medium", valorization_type="CSR"),
        ])

        # Initial prices
        now = utcnow()
        session.add_all([
            PriceMarket(material_code="PET", price_per_tonne=575, currency="EUR", source="SIMULATED", fetched_at=now, variation_pct=0.0),
            PriceMarket(material_code="PEHD", price_per_tonne=710, currency="EUR", source="SIMULATED", fetched_at=now, variation_pct=0.0),
            PriceMarket(material_code="ALU", price_per_tonne=1180, currency="EUR", source="SIMULATED", fetched_at=now, variation_pct=0.0),
            PriceMarket(material_code="ACIER", price_per_tonne=380, currency="EUR", source="SIMULATED", fetched_at=now, variation_pct=0.0),
            PriceMarket(material_code="CARTON", price_per_tonne=145, currency="EUR", source="SIMULATED", fetched_at=now, variation_pct=0.0),
            PriceMarket(material_code="NONREC", price_per_tonne=0, currency="EUR", source="SIMULATED", fetched_at=now, variation_pct=0.0),
            PriceMarket(material_code="ENERGIE", price_per_tonne=65, currency="EUR", source="SIMULATED", fetched_at=now, variation_pct=0.0),
        ])

        # Bale active
        session.add(
            Bale(
                id=1,
                reference="A3-42",
                material_type="PET",
                current_weight_kg=380.0,
                target_weight_kg=500.0,
                purity_pct=94.2,
                status="in_progress",
                started_at=now,
                conveyor_id=3,
            )
        )

        await session.commit()
