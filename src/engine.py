from __future__ import annotations

import random
from collections import deque

import simpy

from config import SimConfig
from graph import START_CITIES, CityGraph
from models import (
    Order,
    OrderStatus,
    Vehicle,
    VehicleStatus,
)


class SimulationEngine:
    """SimPy-based transport logistics simulation."""

    def __init__(self, config: SimConfig):
        self.config = config
        self.graph = CityGraph()
        self.rng = random.Random(42)

        self.env = simpy.Environment()

        self.orders: list[Order] = []
        self.vehicles: list[Vehicle] = []
        self.log_messages: deque[str] = deque(maxlen=500)

        self._order_counter = 0
        self._breakdowns_triggered = False

        self._init_vehicles()
        if config.scenario_logistics_center:
            self._init_logistics_center()

        # Start SimPy processes
        self.env.process(self._order_generator())
        if config.scenario_breakdowns:
            self.env.process(self._breakdown_process())
        if config.scenario_random_events:
            self.env.process(self._road_event_generator())
        self.env.process(self._dispatcher())

    @property
    def time(self) -> float:
        return self.env.now

    def _init_vehicles(self):
        for i in range(self.config.num_vehicles):
            city = START_CITIES[i % len(START_CITIES)]
            v = Vehicle(
                id=i,
                capacity=self.config.vehicle_capacity,
                speed=self.config.vehicle_speed,
                fuel_cost_per_km=self.config.fuel_cost_per_km,
                max_work_hours=self.config.max_driver_hours,
                rest_duration=self.config.rest_duration,
                current_city=city,
            )
            self.vehicles.append(v)

    def _init_logistics_center(self):
        # TODO implement logistics center
        pass

    def step(self, dt: float):
        """Advance simulation by *dt* hours"""
        target = self.env.now + dt
        if target > self.config.simulation_duration:
            target = self.config.simulation_duration
        self.env.run(until=target)

    def _order_generator(self):
        """Poisson-like order arrivals."""
        while True:
            interval = self.rng.expovariate(1.0 / self.config.order_interval_mean)
            yield self.env.timeout(interval)
            if self.env.now >= self.config.simulation_duration:
                return
            self._create_order()

    def _create_order(self):
        cities = list(self.graph.cities.keys())
        src = self.rng.choice(cities)
        dst = self.rng.choice([c for c in cities if c != src])
        weight = self.rng.uniform(
            self.config.order_weight_min, self.config.order_weight_max
        )
        deadline = self.env.now + self.rng.uniform(
            self.config.order_deadline_min, self.config.order_deadline_max
        )
        order = Order(
            id=self._order_counter,
            source=src,
            destination=dst,
            weight=weight,
            deadline=deadline,
            penalty_rate=self.config.penalty_per_hour,
            created_at=self.env.now,
        )
        self.orders.append(order)
        self._order_counter += 1
        self.log(
            f"Order #{order.id}: {src} → {dst}  "
            f"{weight:.0f} kg, due in {deadline - self.env.now:.0f}h"
        )

    def _dispatcher(self):
        """Periodically assign pending orders to available vehicles."""
        while True:
            # TODO Replace current dispatcher algorithm with profits-costs optimizing one
            yield self.env.timeout(0.5)  # check every 0.5 sim-hours
            if self.env.now >= self.config.simulation_duration:
                return
            self._assign_pending_orders()
            if self.config.scenario_logistics_center:
                self._process_hub_orders()

    def _assign_pending_orders(self):
        pending = [o for o in self.orders if o.status == OrderStatus.PENDING]
        if not pending:
            return
        available = [
            v
            for v in self.vehicles
            if v.status == VehicleStatus.IDLE and not v.order_ids
        ]
        for v in available:
            if not pending:
                break
            best_order = None
            best_score = float("inf")
            for order in pending:
                if v.current_load + order.weight > v.capacity:
                    continue
                path, pickup_time = self.graph.dijkstra(
                    v.current_city, order.source, v.speed
                )
                if not path:
                    continue
                _, delivery_time = self.graph.dijkstra(
                    order.source, order.destination, v.speed
                )
                total = pickup_time + delivery_time
                time_left = order.deadline - self.env.now
                urgency = max(0.0, total - time_left)
                score = pickup_time * 2.0 + urgency * 0.5
                if score < best_score:
                    best_score = score
                    best_order = order
            if best_order is not None:
                pending.remove(best_order)
                self._dispatch_vehicle(v, best_order)

    def _dispatch_vehicle(self, vehicle: Vehicle, order: Order):
        """Assign an order and start the vehicle SimPy process."""
        order.status = OrderStatus.ASSIGNED
        order.assigned_vehicle = vehicle.id
        vehicle.order_ids.append(order.id)
        vehicle.current_load += order.weight

        # Build route: current_city -> source -> destination
        if vehicle.current_city == order.source:
            p2, _ = self.graph.dijkstra(order.source, order.destination, vehicle.speed)
            path_full = p2
        else:
            p1, _ = self.graph.dijkstra(
                vehicle.current_city, order.source, vehicle.speed
            )
            p2, _ = self.graph.dijkstra(order.source, order.destination, vehicle.speed)
            path_full = p1 + p2[1:]

        vehicle.route = path_full
        vehicle.route_index = 0
        vehicle.progress = 0.0
        vehicle.pickup_city = order.source
        vehicle.delivery_city = order.destination
        vehicle.status = VehicleStatus.MOVING
        self.log(
            f"Vehicle {vehicle.id} → order #{order.id} "
            f"({order.source} → {order.destination})"
        )
        # Launch vehicle process
        self.env.process(self._vehicle_process(vehicle))

    def _vehicle_process(self, v: Vehicle):
        """Drive a vehicle through its route segment by segment."""
        while v.route_index < len(v.route) - 1:
            if v.status == VehicleStatus.BROKEN_DOWN:
                pass
                # TODO implement broken down behaviour

            ca = v.route[v.route_index]
            cb = v.route[v.route_index + 1]
            dist = self.graph.get_distance(ca, cb)
            if dist is None:
                v.status = VehicleStatus.IDLE
                return

            mult = self.graph.get_multiplier(ca, cb)
            if mult >= 100:
                if not self._reroute_vehicle(v):
                    return
                continue

            eff_speed = v.speed / mult
            seg_time = dist / eff_speed

            # Animate the segment in small increments for UI smoothness
            steps = max(1, int(seg_time / 0.1))
            step_dt = seg_time / steps
            v.progress = 0.0

            for i in range(steps):
                yield self.env.timeout(step_dt)
                v.progress = (i + 1) / steps
                v.hours_worked += step_dt
                km_step = dist / steps
                v.total_distance_km += km_step
                v.total_fuel_cost += km_step * v.fuel_cost_per_km

                # Break out if broken down mid-segment
                if v.status == VehicleStatus.BROKEN_DOWN:
                    break

            if v.status == VehicleStatus.BROKEN_DOWN:
                continue  # loop back to wait for repair

            # Arrived at next city
            v.route_index += 1
            v.progress = 0.0
            v.current_city = cb

            # Check if arrived at pickup city
            if cb == v.pickup_city:
                for oid in v.order_ids:
                    o = self.orders[oid]
                    if o.status == OrderStatus.ASSIGNED:
                        o.status = OrderStatus.IN_TRANSIT

            # Driver rest check (skip if double crew)
            if (
                not self.config.double_crew
                and v.hours_worked >= v.max_work_hours
                and v.route_index < len(v.route) - 1
            ):
                v.status = VehicleStatus.RESTING
                self.log(f"Vehicle {v.id} resting at {v.current_city}")
                yield self.env.timeout(v.rest_duration)
                v.hours_worked = 0.0
                v.status = VehicleStatus.MOVING
                self.log(f"Vehicle {v.id} rested, ready at {v.current_city}")

        self._handle_arrival(v)

    def _handle_arrival(self, v: Vehicle):
        """Vehicle reached end of its route."""
        delivered_ids = list(v.order_ids)
        for oid in delivered_ids:
            o = self.orders[oid]
            if o.status in (OrderStatus.IN_TRANSIT, OrderStatus.ASSIGNED):
                o.status = OrderStatus.DELIVERED
                o.delivered_at = self.env.now
                v.deliveries += 1
                delay_str = (
                    f" (LATE {o.delay:.1f}h, €{o.penalty:.0f})" if o.delay > 0 else ""
                )
                self.log(
                    f"Vehicle {v.id} delivered #{o.id} at {v.current_city}{delay_str}"
                )
        v.order_ids.clear()
        v.current_load = 0.0
        v.route.clear()
        v.route_index = 0
        v.progress = 0.0
        v.pickup_city = ""
        v.delivery_city = ""
        v.status = VehicleStatus.IDLE

    def _reroute_vehicle(self, v: Vehicle) -> bool:
        """Attempt to reroute around a blocked road. Returns True if successful."""
        if not v.route or v.route_index >= len(v.route) - 1:
            return False
        dest = v.route[-1]
        new_path, t = self.graph.dijkstra(v.current_city, dest, v.speed)
        if new_path and t < float("inf"):
            v.route = new_path
            v.route_index = 0
            v.progress = 0.0
            self.log(f"Vehicle {v.id} rerouted via {' → '.join(new_path[:4])}…")
            return True
        self.log(f"Vehicle {v.id} stuck – no route to {dest}")
        v.status = VehicleStatus.IDLE
        return False

    def _breakdown_process(self):
        """Wait until trigger time, then break down K vehicles."""
        yield self.env.timeout(self.config.breakdown_trigger_time)
        if self._breakdowns_triggered:
            return
        self._breakdowns_triggered = True

        # TODO add breakdowns

    def _road_event_generator(self):
        """Periodically create random road events."""
        while True:
            yield self.env.timeout(1.0)
            if self.env.now >= self.config.simulation_duration:
                return

            # TODO implement road event generator

    def get_vehicle_position(self, v: Vehicle) -> tuple[float, float]:
        """Return interpolated (lat, lon) for a vehicle."""
        if v.status in (
            VehicleStatus.IDLE,
            VehicleStatus.RESTING,
            VehicleStatus.BROKEN_DOWN,
        ):
            return self.graph.cities[v.current_city]
        if not v.route or v.route_index >= len(v.route) - 1:
            return self.graph.cities[v.current_city]
        ca = v.route[v.route_index]
        cb = v.route[v.route_index + 1]
        la, lo_a = self.graph.cities[ca]
        lb, lo_b = self.graph.cities[cb]
        p = max(0.0, min(1.0, v.progress))
        return (la + p * (lb - la), lo_a + p * (lo_b - lo_a))

    def get_stats(self) -> dict:
        delivered = [o for o in self.orders if o.status == OrderStatus.DELIVERED]
        on_time = [o for o in delivered if o.delay == 0]
        late = [o for o in delivered if o.delay > 0]
        total_penalty = sum(o.penalty for o in delivered)
        total_fuel = sum(v.total_fuel_cost for v in self.vehicles)
        total_repair = sum(v.total_repair_cost for v in self.vehicles)
        moving = sum(1 for v in self.vehicles if v.status == VehicleStatus.MOVING)
        idle = sum(1 for v in self.vehicles if v.status == VehicleStatus.IDLE)
        broken = sum(1 for v in self.vehicles if v.status == VehicleStatus.BROKEN_DOWN)
        resting = sum(1 for v in self.vehicles if v.status == VehicleStatus.RESTING)
        pending = sum(1 for o in self.orders if o.status == OrderStatus.PENDING)
        return {
            "time": self.env.now,
            "total_orders": len(self.orders),
            "delivered": len(delivered),
            "on_time": len(on_time),
            "late": len(late),
            "pending": pending,
            "total_delay_h": sum(o.delay for o in late),
            "total_penalty": total_penalty,
            "total_fuel": total_fuel,
            "total_repair": total_repair,
            "total_cost": total_penalty + total_fuel + total_repair,
            "vehicles_moving": moving,
            "vehicles_idle": idle,
            "vehicles_broken": broken,
            "vehicles_resting": resting,
        }

    def log(self, msg: str):
        stamp = f"[{self.env.now:06.1f}h] "
        self.log_messages.append(stamp + msg)
