from datetime import date

from geoalchemy2 import Geography
from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    score_scale: Mapped[str] = mapped_column(String(200))


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
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    source_id: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(300))
    borough: Mapped[str | None] = mapped_column(String(50), index=True)
    zip: Mapped[str | None] = mapped_column(String(10))
    cuisine: Mapped[str | None] = mapped_column(String(100), index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    geom = mapped_column(Geography("POINT", srid=4326, spatial_index=False), nullable=True)
    latest_grade: Mapped[str | None] = mapped_column(String(5), index=True)
    latest_score: Mapped[int | None] = mapped_column(Integer)
    latest_rating: Mapped[str | None] = mapped_column(String(20))
    latest_inspected_at: Mapped[date | None] = mapped_column(Date)

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
    raw_grade: Mapped[str | None] = mapped_column(String(5))
    rating: Mapped[str | None] = mapped_column(String(20))

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
