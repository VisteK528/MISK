from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


@dataclass
class Waypoint:
    city: str
    order_id: int
    action: str  # "pickup" | "delivery"


class VehicleStatus(Enum):
    IDLE = "idle"
    MOVING = "moving"
    BROKEN_DOWN = "broken_down"
    RESTING = "resting"


class OrderStatus(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    AT_HUB = "at_hub"
    DELIVERED = "delivered"


@dataclass
class Order:
    id: int
    source: str
    destination: str
    weight: float
    deadline: float  # sim-time when due
    penalty_rate: float  # EUR per hour late
    created_at: float
    revenue: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    assigned_vehicle: Optional[int] = None
    delivered_at: Optional[float] = None
    via_hub: bool = False

    @property
    def delay(self) -> float:
        if self.delivered_at is not None and self.delivered_at > self.deadline:
            return self.delivered_at - self.deadline
        return 0.0

    @property
    def penalty(self) -> float:
        return self.delay * self.penalty_rate


@dataclass
class Vehicle:
    id: int
    capacity: float
    speed: float
    fuel_cost_per_km: float
    max_work_hours: float
    rest_duration: float

    current_city: str
    status: VehicleStatus = VehicleStatus.IDLE

    route: list[str] = field(default_factory=list)
    route_index: int = 0
    progress: float = 0.0  # 0-1 along current segment

    waypoints: list[Waypoint] = field(default_factory=list)
    waypoint_index: int = 0

    order_ids: list[int] = field(default_factory=list)
    current_load: float = 0.0

    hours_worked: float = 0.0
    rest_until: float = 0.0

    total_distance_km: float = 0.0
    total_fuel_cost: float = 0.0
    total_repair_cost: float = 0.0
    deliveries: int = 0
