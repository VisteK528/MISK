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
    Waypoint,
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

        self.env.process(self._order_generator())
        if config.scenario_breakdowns:
            self.env.process(self._breakdown_process())
        if config.scenario_random_events:
            self.env.process(self._road_event_generator())
        self.env.process(self._dispatcher())

    @property
    def time(self) -> float:
        return self.env.now

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Simulation control
    # ------------------------------------------------------------------

    def step(self, dt: float):
        """Advance simulation by *dt* hours."""
        target = self.env.now + dt
        if target > self.config.simulation_duration:
            target = self.config.simulation_duration
        self.env.run(until=target)

    # ------------------------------------------------------------------
    # Order generation
    # ------------------------------------------------------------------

    def _order_generator(self):
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

        _, delivery_h = self.graph.dijkstra(src, dst, self.config.vehicle_speed)
        delivery_km = delivery_h * self.config.vehicle_speed
        revenue = self.config.base_revenue + self.config.revenue_per_km * delivery_km

        order = Order(
            id=self._order_counter,
            source=src,
            destination=dst,
            weight=weight,
            deadline=deadline,
            penalty_rate=self.config.penalty_per_hour,
            created_at=self.env.now,
            revenue=revenue,
        )
        self.orders.append(order)
        self._order_counter += 1
        self.log(
            f"Order #{order.id}: {src}→{dst}  "
            f"{weight:.0f} kg, due in {deadline - self.env.now:.0f}h, "
            f"revenue €{revenue:.0f}"
        )

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    def _dispatcher(self):
        while True:
            yield self.env.timeout(0.5)
            if self.env.now >= self.config.simulation_duration:
                return
            self._assign_pending_orders()
            if self.config.scenario_logistics_center:
                self._process_hub_orders()

    def _assign_pending_orders(self):
        """
        Profit-maximising dispatcher using cheapest insertion.

        For each idle vehicle, greedily pack orders as long as the marginal
        profit of adding the next order is positive.  All candidates are
        scored simultaneously so the globally best (vehicle, order) pair is
        always chosen first.
        """
        pending = [o for o in self.orders if o.status == OrderStatus.PENDING]
        if not pending:
            return

        idle_vehicles = [
            v
            for v in self.vehicles
            if v.status == VehicleStatus.IDLE and not v.order_ids
        ]

        for v in idle_vehicles:
            if not pending:
                break
            # Keep adding orders to this vehicle while it's profitable
            while pending:
                best_profit = 0.0  # only accept positive-profit additions
                best_order: Order | None = None
                best_wps: list[Waypoint] = []

                for order in pending:
                    profit, new_wps = self._cheapest_insertion(v, order)
                    if profit > best_profit:
                        best_profit = profit
                        best_order = order
                        best_wps = new_wps

                if best_order is None:
                    break  # nothing profitable to add

                pending.remove(best_order)
                best_order.status = OrderStatus.ASSIGNED
                best_order.assigned_vehicle = v.id
                v.order_ids.append(best_order.id)
                v.current_load += best_order.weight
                v.waypoints = best_wps
                self.log(
                    f"Queued order #{best_order.id} "
                    f"({best_order.source}→{best_order.destination}) "
                    f"for vehicle {v.id}  profit €{best_profit:.0f}"
                )

            if v.order_ids:
                self._launch_vehicle(v)

    # ------------------------------------------------------------------
    # Route helpers
    # ------------------------------------------------------------------

    def _path_km(self, path: list[str]) -> float:
        """Total road distance in km for a city path."""
        km = 0.0
        for i in range(len(path) - 1):
            d = self.graph.get_distance(path[i], path[i + 1])
            km += d or 0.0
        return km

    def _build_route(self, waypoints: list[Waypoint], start_city: str) -> list[str]:
        """
        Concatenate Dijkstra shortest-paths between consecutive waypoints.
        Returns an empty list if any segment has no valid path.
        """
        route: list[str] = [start_city]
        current = start_city
        for wp in waypoints:
            if wp.city == current:
                continue
            seg, _ = self.graph.dijkstra(current, wp.city, self.config.vehicle_speed)
            if not seg:
                return []
            route.extend(seg[1:])
            current = wp.city
        return route

    def _delivery_eta(
        self,
        start_city: str,
        waypoints: list[Waypoint],
        order_id: int,
        speed: float,
    ) -> float:
        """Estimated arrival time at delivery waypoint for a given order."""
        current = start_city
        t = self.env.now
        for wp in waypoints:
            if wp.city != current:
                _, seg_h = self.graph.dijkstra(current, wp.city, speed)
                t += seg_h
                current = wp.city
            if wp.action == "delivery" and wp.order_id == order_id:
                return t
        return float("inf")

    def _cheapest_insertion(
        self, v: Vehicle, order: Order
    ) -> tuple[float, list[Waypoint]]:
        """
        Find the insertion position for (pickup, delivery) in v's current
        waypoints list that maximises profit.

        profit = order.revenue - extra_fuel_cost - expected_penalty

        Returns (best_profit, new_waypoints).  Returns (-inf, []) if the
        order cannot be added (capacity exceeded, no valid path).
        """
        if v.current_load + order.weight > v.capacity:
            return float("-inf"), []

        wps = list(v.waypoints)
        n = len(wps)

        current_route = self._build_route(wps, v.current_city)
        current_km = self._path_km(current_route)

        best_profit = float("-inf")
        best_wps: list[Waypoint] = []

        pickup_wp = Waypoint(order.source, order.id, "pickup")
        delivery_wp = Waypoint(order.destination, order.id, "delivery")

        for i in range(n + 1):  # insertion index for pickup
            for j in range(i, n + 1):  # insertion index for delivery (>= pickup)
                candidate = wps[:i] + [pickup_wp] + wps[i:j] + [delivery_wp] + wps[j:]
                new_route = self._build_route(candidate, v.current_city)
                if not new_route:
                    continue

                extra_km = self._path_km(new_route) - current_km
                fuel_cost = extra_km * v.fuel_cost_per_km

                delivery_eta = self._delivery_eta(
                    v.current_city, candidate, order.id, v.speed
                )
                penalty_risk = (
                    max(0.0, delivery_eta - order.deadline) * order.penalty_rate
                )

                profit = order.revenue - fuel_cost - penalty_risk

                if profit > best_profit:
                    best_profit = profit
                    best_wps = candidate

        return best_profit, best_wps

    # ------------------------------------------------------------------
    # Vehicle launch
    # ------------------------------------------------------------------

    def _launch_vehicle(self, v: Vehicle):
        """Build final route from waypoints and start the SimPy process."""
        route = self._build_route(v.waypoints, v.current_city)
        if not route:
            self.log(f"Vehicle {v.id}: could not build route, staying idle")
            v.order_ids.clear()
            v.waypoints.clear()
            v.current_load = 0.0
            return

        v.route = route
        v.route_index = 0
        v.progress = 0.0
        v.waypoint_index = 0
        v.status = VehicleStatus.MOVING
        cities = " → ".join(wp.city for wp in v.waypoints[:6])
        self.log(f"Vehicle {v.id} departing: {cities}")
        self.env.process(self._vehicle_process(v))

    # ------------------------------------------------------------------
    # Vehicle process
    # ------------------------------------------------------------------

    def _vehicle_process(self, v: Vehicle):
        """Drive a vehicle through its multi-stop route segment by segment."""
        # Handle pickups/deliveries at the starting city
        self._process_waypoints_at(v, v.current_city)

        while v.route_index < len(v.route) - 1:
            if v.status == VehicleStatus.BROKEN_DOWN:
                pass
                # TODO implement broken-down behaviour (Scenario 2)

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

                if v.status == VehicleStatus.BROKEN_DOWN:
                    break

            if v.status == VehicleStatus.BROKEN_DOWN:
                continue

            v.route_index += 1
            v.progress = 0.0
            v.current_city = cb

            self._process_waypoints_at(v, cb)

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

    def _process_waypoints_at(self, v: Vehicle, city: str):
        """Execute all pending waypoints whose city matches the current city."""
        while (
            v.waypoint_index < len(v.waypoints)
            and v.waypoints[v.waypoint_index].city == city
        ):
            wp = v.waypoints[v.waypoint_index]
            order = self.orders[wp.order_id]

            if wp.action == "pickup":
                if order.status == OrderStatus.ASSIGNED:
                    order.status = OrderStatus.IN_TRANSIT
                    self.log(f"Vehicle {v.id} picked up #{order.id} at {city}")

            else:  # delivery
                if order.status in (OrderStatus.IN_TRANSIT, OrderStatus.ASSIGNED):
                    order.status = OrderStatus.DELIVERED
                    order.delivered_at = self.env.now
                    v.deliveries += 1
                    v.current_load = max(0.0, v.current_load - order.weight)
                    if order.id in v.order_ids:
                        v.order_ids.remove(order.id)
                    result = (
                        f"LATE {order.delay:.1f}h  -€{order.penalty:.0f}"
                        if order.delay > 0
                        else f"+€{order.revenue:.0f}"
                    )
                    self.log(
                        f"Vehicle {v.id} delivered #{order.id} at {city}  {result}"
                    )

            v.waypoint_index += 1

    def _handle_arrival(self, v: Vehicle):
        """Clean up after a vehicle completes its full route."""
        # Deliver any orders that somehow weren't delivered mid-route
        for oid in list(v.order_ids):
            o = self.orders[oid]
            if o.status in (OrderStatus.IN_TRANSIT, OrderStatus.ASSIGNED):
                o.status = OrderStatus.DELIVERED
                o.delivered_at = self.env.now
                v.deliveries += 1
                delay_str = (
                    f" LATE {o.delay:.1f}h  -€{o.penalty:.0f}"
                    if o.delay > 0
                    else f"  +€{o.revenue:.0f}"
                )
                self.log(
                    f"Vehicle {v.id} delivered #{o.id} at {v.current_city}{delay_str}"
                )

        v.order_ids.clear()
        v.current_load = 0.0
        v.route.clear()
        v.route_index = 0
        v.progress = 0.0
        v.waypoints.clear()
        v.waypoint_index = 0
        v.status = VehicleStatus.IDLE

    # ------------------------------------------------------------------
    # Rerouting (blocked roads)
    # ------------------------------------------------------------------

    def _reroute_vehicle(self, v: Vehicle) -> bool:
        """Rebuild route from current city through remaining waypoints."""
        remaining = v.waypoints[v.waypoint_index :]
        if not remaining:
            v.status = VehicleStatus.IDLE
            return False

        new_route = self._build_route(remaining, v.current_city)
        if new_route:
            v.route = new_route
            v.route_index = 0
            v.progress = 0.0
            self.log(f"Vehicle {v.id} rerouted via {' → '.join(new_route[:4])}…")
            return True

        self.log(f"Vehicle {v.id} stuck – no route to {remaining[0].city}")
        v.status = VehicleStatus.IDLE
        return False

    # ------------------------------------------------------------------
    # Scenarios
    # ------------------------------------------------------------------

    def _breakdown_process(self):
        """Wait until trigger time, then break down K vehicles."""
        yield self.env.timeout(self.config.breakdown_trigger_time)
        if self._breakdowns_triggered:
            return
        self._breakdowns_triggered = True

        # TODO add breakdowns (Scenario 2)

    def _road_event_generator(self):
        """Periodically create random road events."""
        while True:
            yield self.env.timeout(1.0)
            if self.env.now >= self.config.simulation_duration:
                return

            # TODO implement road event generator (Scenario 4)

    def _process_hub_orders(self):
        # TODO implement logistics hub order processing (Scenario 3)
        pass

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

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
        total_revenue = sum(o.revenue for o in delivered)
        total_fuel = sum(v.total_fuel_cost for v in self.vehicles)
        total_repair = sum(v.total_repair_cost for v in self.vehicles)
        vehicles_moving = sum(
            1 for v in self.vehicles if v.status == VehicleStatus.MOVING
        )
        vehicles_idle = sum(1 for v in self.vehicles if v.status == VehicleStatus.IDLE)
        vehicles_broken = sum(
            1 for v in self.vehicles if v.status == VehicleStatus.BROKEN_DOWN
        )
        vehicles_resting = sum(
            1 for v in self.vehicles if v.status == VehicleStatus.RESTING
        )
        pending = sum(1 for o in self.orders if o.status == OrderStatus.PENDING)
        total_cost = total_fuel + total_penalty + total_repair
        return {
            "time": self.env.now,
            "total_orders": len(self.orders),
            "delivered": len(delivered),
            "on_time": len(on_time),
            "late": len(late),
            "pending": pending,
            "total_delay_h": sum(o.delay for o in late),
            "total_revenue": total_revenue,
            "total_penalty": total_penalty,
            "total_fuel": total_fuel,
            "total_repair": total_repair,
            "total_cost": total_cost,
            "net_profit": total_revenue - total_cost,
            "vehicles_moving": vehicles_moving,
            "vehicles_idle": vehicles_idle,
            "vehicles_resting": vehicles_resting,
            "vehicles_broken": vehicles_broken,
        }

    def log(self, msg: str):
        stamp = f"[{self.env.now:06.1f}h] "
        self.log_messages.append(stamp + msg)
