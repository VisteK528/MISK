from __future__ import annotations

import dataclasses
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
        self.rng = random.Random(config.seed)

        self.env = simpy.Environment()

        self.orders: list[Order] = []
        self.vehicles: list[Vehicle] = []
        self.log_messages: deque[str] = deque(maxlen=500)

        self._order_counter = 0
        self._breakdowns_triggered = False
        self._breakdown_events: int = 0
        self._road_event_count: int = 0
        self.profit_history: list[dict] = []

        self._init_vehicles()
        if config.scenario_logistics_center:
            self._init_logistics_center()

        self.env.process(self._order_generator())
        if config.scenario_breakdowns:
            self.env.process(self._breakdown_process())
        if config.scenario_random_events:
            self.env.process(self._road_event_generator())
        self.env.process(self._dispatcher())
        self.env.process(self._stats_recorder())

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
        hub = self.config.hub_city
        if hub not in self.graph.cities:
            raise ValueError(f"Hub city '{hub}' not found in graph")
        self.log(
            f"Centrum logistyczne otwarte w {hub} "
            f"(~{self.config.hub_via_rate * 100:.0f}% zlecen przez hub)"
        )

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

        hub = self.config.hub_city
        via_hub = (
            self.config.scenario_logistics_center
            and src != hub
            and dst != hub
            and self.rng.random() < self.config.hub_via_rate
        )

        order = Order(
            id=self._order_counter,
            source=src,
            destination=dst,
            weight=weight,
            deadline=deadline,
            penalty_rate=self.config.penalty_per_hour,
            created_at=self.env.now,
            revenue=revenue,
            via_hub=via_hub,
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

        direct = [o for o in pending if not o.via_hub]
        hub_leg1 = [o for o in pending if o.via_hub]

        idle_vehicles = [
            v
            for v in self.vehicles
            if v.status == VehicleStatus.IDLE and not v.order_ids
        ]

        for v in idle_vehicles:
            if not direct:
                break
            # Keep adding orders to this vehicle while it's profitable
            while direct:
                best_profit = 0.0  # only accept positive-profit additions
                best_order: Order | None = None
                best_wps: list[Waypoint] = []

                for order in direct:
                    profit, new_wps = self._cheapest_insertion(v, order)
                    if profit > best_profit:
                        best_profit = profit
                        best_order = order
                        best_wps = new_wps

                if best_order is None:
                    break  # nothing profitable to add

                direct.remove(best_order)
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

        if hub_leg1:
            self._assign_hub_leg1_orders(hub_leg1)

    def _assign_hub_leg1_orders(self, hub_orders: list[Order]):
        """Assign the source → hub leg for via_hub orders to idle vehicles."""
        hub = self.config.hub_city
        idle_vehicles = [
            v
            for v in self.vehicles
            if v.status == VehicleStatus.IDLE and not v.order_ids
        ]
        for v in idle_vehicles:
            if not hub_orders:
                break
            for order in list(hub_orders):
                if v.current_load + order.weight > v.capacity:
                    continue
                seg, leg_h = self.graph.dijkstra(order.source, hub, v.speed)
                if not seg:
                    continue
                leg_km = leg_h * v.speed
                if order.revenue / 2 < leg_km * v.fuel_cost_per_km:
                    continue  # leg 1 alone not worth it
                order.status = OrderStatus.ASSIGNED
                order.assigned_vehicle = v.id
                v.order_ids.append(order.id)
                v.current_load += order.weight
                v.waypoints = [
                    Waypoint(order.source, order.id, "pickup"),
                    Waypoint(hub, order.id, "delivery"),
                ]
                hub_orders.remove(order)
                self.log(
                    f"Hub leg-1: order #{order.id} ({order.source}→{hub}) "
                    f"assigned to vehicle {v.id}"
                )
                self._launch_vehicle(v)
                break

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
                wait = max(0.0, v.repair_until - self.env.now)
                if wait > 0:
                    yield self.env.timeout(wait)
                if v.breakdown_type == "out_of_service":
                    v.status = VehicleStatus.IDLE
                    v.breakdown_type = None
                    return
                v.status = VehicleStatus.MOVING
                v.breakdown_type = None
                self.log(f"Vehicle {v.id} repaired, resuming at {v.current_city}")

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
                if (
                    order.via_hub
                    and order.status == OrderStatus.IN_TRANSIT
                    and city == self.config.hub_city
                ):
                    # First leg complete – cargo now waiting at hub
                    order.status = OrderStatus.AT_HUB
                    v.current_load = max(0.0, v.current_load - order.weight)
                    if order.id in v.order_ids:
                        v.order_ids.remove(order.id)
                    self.log(
                        f"Vehicle {v.id} dropped #{order.id} at hub ({city}), "
                        f"awaiting onward transport"
                    )
                elif order.status in (OrderStatus.IN_TRANSIT, OrderStatus.ASSIGNED):
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

        candidates = [v for v in self.vehicles if v.status == VehicleStatus.MOVING]
        if not candidates:
            candidates = [
                v for v in self.vehicles if v.status != VehicleStatus.BROKEN_DOWN
            ]

        k = min(self.config.breakdown_k, len(candidates))
        broken = self.rng.sample(candidates, k)
        self.log(
            f"=== BREAKDOWN EVENT: {k} vehicle(s) fail at t={self.env.now:.1f}h ==="
        )
        for v in broken:
            self._apply_breakdown(v)

    def _apply_breakdown(self, v: Vehicle):
        r = self.rng.random()
        driver_p = self.config.repair_driver_prob
        mobile_p = self.config.repair_mobile_prob
        if r < driver_p:
            v.breakdown_type = "driver"
            repair_time = self.config.repair_driver_delay
            self.log(
                f"Vehicle {v.id} broke down at {v.current_city} – "
                f"driver self-repair ({repair_time:.0f}h delay)"
            )
        elif r < driver_p + mobile_p:
            v.breakdown_type = "mobile"
            repair_time = self.config.mobile_service_delay
            v.total_repair_cost += self.config.mobile_service_cost
            self.log(
                f"Vehicle {v.id} broke down – mobile service called "
                f"(€{self.config.mobile_service_cost:.0f}, {repair_time:.0f}h delay)"
            )
        else:
            v.breakdown_type = "out_of_service"
            repair_time = self.config.out_of_service_duration
            v.total_repair_cost += self.config.out_of_service_cost
            self.log(
                f"Vehicle {v.id} out of service for "
                f"{self.config.out_of_service_duration / 24:.0f} days "
                f"(€{self.config.out_of_service_cost:.0f}) – orders redistributed"
            )
            self._return_orders_to_pending(v)

        v.status = VehicleStatus.BROKEN_DOWN
        v.repair_until = self.env.now + repair_time
        self._breakdown_events += 1

    def _return_orders_to_pending(self, v: Vehicle):
        """Return undelivered orders to pending so the dispatcher can reassign them."""
        for oid in list(v.order_ids):
            order = self.orders[oid]
            if order.status not in (OrderStatus.DELIVERED,):
                order.status = OrderStatus.PENDING
                order.assigned_vehicle = None
                self.log(
                    f"Order #{oid} returned to pending (vehicle {v.id} out of service)"
                )
        v.order_ids.clear()
        v.waypoints.clear()
        v.route.clear()
        v.route_index = 0
        v.current_load = 0.0

    def _road_event_generator(self):
        """Periodically create random road events."""
        while True:
            interval = self.rng.expovariate(1.0 / self.config.event_interval_mean)
            yield self.env.timeout(interval)
            if self.env.now >= self.config.simulation_duration:
                return
            self._trigger_road_event()

    def _trigger_road_event(self):
        edges = list(self.graph.get_all_road_keys())
        c1, c2 = self.rng.choice(edges)

        r = self.rng.random()
        # weights: weather 50%, accident 30%, closure 20%
        if r < 0.50:
            event_type = "weather"
            mult = self.rng.uniform(
                self.config.event_weather_mult * 0.8,
                self.config.event_weather_mult * 1.2,
            )
            duration = self.rng.expovariate(
                1.0 / self.config.event_weather_duration_mean
            )
        elif r < 0.80:
            event_type = "accident"
            mult = self.rng.uniform(
                self.config.event_accident_mult * 0.8,
                self.config.event_accident_mult * 1.2,
            )
            duration = self.rng.expovariate(
                1.0 / self.config.event_accident_duration_mean
            )
        else:
            event_type = "closure"
            mult = 100.0
            duration = self.rng.expovariate(
                1.0 / self.config.event_closure_duration_mean
            )

        self._road_event_count += 1
        self.graph.set_multiplier(c1, c2, mult)
        self.log(
            f"Road event [{event_type}] {c1}–{c2}: "
            f"{'BLOCKED' if mult >= 100 else f'x{mult:.1f} slower'} "
            f"for ~{duration:.0f}h"
        )

        # Reroute any vehicle currently on this segment
        for v in self.vehicles:
            if v.status == VehicleStatus.MOVING and v.route_index < len(v.route) - 1:
                ca = v.route[v.route_index]
                cb = v.route[v.route_index + 1]
                if tuple(sorted([ca, cb])) == tuple(sorted([c1, c2])):
                    self._reroute_vehicle(v)

        self.env.process(self._restore_road(c1, c2, duration))

    def _restore_road(self, c1: str, c2: str, duration: float):
        yield self.env.timeout(duration)
        self.graph.set_multiplier(c1, c2, 1.0)
        self.log(f"Road cleared: {c1}–{c2}")

    def _process_hub_orders(self):
        """Assign hub→destination (leg 2) for orders waiting at the logistics center."""
        hub = self.config.hub_city
        hub_orders = [o for o in self.orders if o.status == OrderStatus.AT_HUB]
        if not hub_orders:
            return

        idle_at_hub = [
            v
            for v in self.vehicles
            if v.status == VehicleStatus.IDLE
            and v.current_city == hub
            and not v.order_ids
        ]

        for v in idle_at_hub:
            if not hub_orders:
                break
            for order in list(hub_orders):
                if v.current_load + order.weight > v.capacity:
                    continue
                seg, _ = self.graph.dijkstra(hub, order.destination, v.speed)
                if not seg:
                    continue
                order.status = OrderStatus.ASSIGNED
                order.assigned_vehicle = v.id
                v.order_ids.append(order.id)
                v.current_load += order.weight
                v.waypoints = [
                    Waypoint(hub, order.id, "pickup"),
                    Waypoint(order.destination, order.id, "delivery"),
                ]
                hub_orders.remove(order)
                self.log(
                    f"Hub leg-2: order #{order.id} ({hub}→{order.destination}) "
                    f"assigned to vehicle {v.id}"
                )
                self._launch_vehicle(v)
                break

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
        hub_at_hub = sum(1 for o in self.orders if o.status == OrderStatus.AT_HUB)
        hub_via_delivered = sum(
            1 for o in self.orders if o.status == OrderStatus.DELIVERED and o.via_hub
        )
        active_road_events = sum(
            1
            for (c1, c2) in self.graph.get_all_road_keys()
            if self.graph.get_multiplier(c1, c2) > 1.0
        )
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
            "breakdown_events": self._breakdown_events,
            "hub_at_hub": hub_at_hub,
            "hub_via_delivered": hub_via_delivered,
            "active_road_events": active_road_events,
            "road_events_total": self._road_event_count,
        }

    def _stats_recorder(self):
        """Sample revenue/cost once per sim-hour for the profit time series."""
        while True:
            yield self.env.timeout(1.0)
            if self.env.now > self.config.simulation_duration:
                return
            s = self.get_stats()
            self.profit_history.append(
                {
                    "time": round(self.env.now, 2),
                    "revenue": round(s["total_revenue"], 2),
                    "cost": round(s["total_cost"], 2),
                }
            )

    def export_data(self) -> dict:
        """Return all simulation state as a JSON-serialisable dict."""
        config_data = dataclasses.asdict(self.config)

        orders_data = [
            {
                "id": o.id,
                "source": o.source,
                "destination": o.destination,
                "weight_kg": round(o.weight, 2),
                "created_at_h": round(o.created_at, 2),
                "deadline_h": round(o.deadline, 2),
                "penalty_rate": o.penalty_rate,
                "revenue": round(o.revenue, 2),
                "status": o.status.value,
                "assigned_vehicle": o.assigned_vehicle,
                "delivered_at_h": round(o.delivered_at, 2)
                if o.delivered_at is not None
                else None,
                "via_hub": o.via_hub,
                "delay_h": round(o.delay, 2),
                "penalty": round(o.penalty, 2),
                "net": round(o.revenue - o.penalty, 2),
            }
            for o in self.orders
        ]

        vehicles_data = [
            {
                "id": v.id,
                "final_city": v.current_city,
                "status": v.status.value,
                "total_distance_km": round(v.total_distance_km, 2),
                "total_fuel_cost": round(v.total_fuel_cost, 2),
                "total_repair_cost": round(v.total_repair_cost, 2),
                "deliveries": v.deliveries,
            }
            for v in self.vehicles
        ]

        return {
            "config": config_data,
            "summary": self.get_stats(),
            "orders": orders_data,
            "vehicles": vehicles_data,
            "profit_history": self.profit_history,
            "event_log": list(self.log_messages),
        }

    def log(self, msg: str):
        stamp = f"[{self.env.now:06.1f}h] "
        self.log_messages.append(stamp + msg)
