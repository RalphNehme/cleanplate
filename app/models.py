from datetime import date, datetime

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    score_scale: Mapped[str] = mapped_column(String(300))
    official_label: Mapped[str] = mapped_column(String(50))
    center_lat: Mapped[float] = mapped_column(Float)
    center_lon: Mapped[float] = mapped_column(Float)
    zoom: Mapped[float] = mapped_column(Float)
    source_name: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(300))


class Restaurant(Base):
    __tablename__ = "restaurants"
    __table_args__ = (
        UniqueConstraint("city_id", "source_id"),
        Index(
            "ix_restaurants_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(300))
    borough: Mapped[str | None] = mapped_column(String(50), index=True)
    zip: Mapped[str | None] = mapped_column(String(10))
    cuisine: Mapped[str | None] = mapped_column(String(100), index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    geom = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    latest_grade: Mapped[str | None] = mapped_column(String(30), index=True)
    latest_score: Mapped[int | None] = mapped_column(Integer)
    latest_rating: Mapped[str | None] = mapped_column(String(20))
    latest_inspected_at: Mapped[date | None] = mapped_column(Date)
    hygiene_score: Mapped[int | None] = mapped_column(Integer, index=True)
    osm_id: Mapped[str | None] = mapped_column(String(30))
    osm_cuisine: Mapped[str | None] = mapped_column(String(100))
    diet_tags: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(500))
    food_score: Mapped[int | None] = mapped_column(Integer, index=True)
    food_source: Mapped[str | None] = mapped_column(String(20))
    food_reports_count: Mapped[int] = mapped_column(Integer, default=0)
    reported_oil: Mapped[str | None] = mapped_column(String(20))

    city: Mapped[City] = relationship()
    menu: Mapped["Menu | None"] = relationship()
    analysis: Mapped["MenuAnalysis | None"] = relationship()
    inspections: Mapped[list["Inspection"]] = relationship(
        back_populates="restaurant", order_by="Inspection.inspected_at.desc()"
    )


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (UniqueConstraint("restaurant_id", "inspected_at", "type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    inspected_at: Mapped[date] = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(100))
    action: Mapped[str | None] = mapped_column(Text)
    raw_score: Mapped[int | None] = mapped_column(Integer)
    raw_grade: Mapped[str | None] = mapped_column(String(30))
    rating: Mapped[str | None] = mapped_column(String(20))
    hygiene_score: Mapped[int | None] = mapped_column(Integer)

    restaurant: Mapped[Restaurant] = relationship(back_populates="inspections")
    violations: Mapped[list["Violation"]] = relationship(back_populates="inspection")


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str | None] = mapped_column(String(10), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    critical: Mapped[bool] = mapped_column(Boolean, default=False)

    inspection: Mapped[Inspection] = relationship(back_populates="violations")


class FoodReport(Base):
    __tablename__ = "food_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), index=True
    )
    oil: Mapped[str | None] = mapped_column(String(20))
    ingredients: Mapped[str | None] = mapped_column(String(20))
    healthy_options: Mapped[str | None] = mapped_column(String(20))
    score: Mapped[int | None] = mapped_column(Integer)
    reporter_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str] = mapped_column(String(20), index=True)
    url: Mapped[str | None] = mapped_column(String(1000))
    text: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(String(300))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MenuAnalysis(Base):
    __tablename__ = "menu_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), unique=True
    )
    model: Mapped[str] = mapped_column(String(50))
    text_hash: Mapped[str] = mapped_column(String(64))
    score: Mapped[int | None] = mapped_column(Integer)
    cuisine: Mapped[str | None] = mapped_column(String(100))
    summary: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
