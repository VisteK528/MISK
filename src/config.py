from dataclasses import dataclass


@dataclass
class SimConfig:
    # Fleet
    num_vehicles: int = 8
    vehicle_capacity: float = 20_000  # kg
    vehicle_speed: float = 80  # km/h average
    fuel_cost_per_km: float = 1.5  # EUR/km
    max_driver_hours: float = 10  # hours before mandatory rest
    rest_duration: float = 9  # hours of rest
    double_crew: bool = False  # two drivers – no rest needed

    # Orders
    order_interval_mean: float = 3.0  # hours between orders on average
    order_weight_min: float = 500  # kg
    order_weight_max: float = 5000  # kg
    order_deadline_min: float = 24  # hours
    order_deadline_max: float = 96  # hours
    penalty_per_hour: float = 50  # EUR per hour late
    base_revenue: float = 200.0  # EUR flat fee per order
    revenue_per_km: float = 2.0  # EUR per km of delivery route

    # Simulation
    simulation_duration: float = 168
    time_step: float = 0.1

    # Scenario flags (toggled from UI)
    scenario_breakdowns: bool = False
    scenario_logistics_center: bool = False
    scenario_random_events: bool = False
