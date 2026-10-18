from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


@dataclass
class ViolationRecord:
    code: str | None
    description: str | None
    critical: bool


@dataclass
class InspectionRecord:
    inspected_at: date
    type: str
    action: str | None
    raw_score: int | None
    raw_grade: str | None
    rating: str | None
    violations: list[ViolationRecord] = field(default_factory=list)
    hygiene_score: int | None = None


@dataclass
class RestaurantRecord:
    source_id: str
    name: str
    address: str | None
    borough: str | None
    zip: str | None
    cuisine: str | None
    phone: str | None
    lat: float | None
    lon: float | None
    inspections: list[InspectionRecord] = field(default_factory=list)


class CityAdapter(Protocol):
    slug: str

    def restaurants(self, since: date | None = None) -> Iterator[RestaurantRecord]: ...
