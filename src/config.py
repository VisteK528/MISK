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
    seed: int = 42

    # Scenario flags (toggled from UI)
    scenario_breakdowns: bool = False
    scenario_logistics_center: bool = False
    scenario_random_events: bool = False

    # Scenario 2 – vehicle breakdowns
    breakdown_k: int = 2  # number of vehicles that fail
    breakdown_trigger_time: float = 24.0  # hours into sim before failures occur
    repair_driver_prob: float = 0.5  # probability of type-a (driver self-repair)
    repair_mobile_prob: float = 0.3  # probability of type-b (mobile service)
    repair_driver_delay: float = 3.0  # hours lost for driver self-repair
    mobile_service_delay: float = 6.0  # hours lost waiting for mobile service
    mobile_service_cost: float = 500.0  # EUR cost of mobile service call
    out_of_service_duration: float = 72.0  # hours vehicle is out (M days × 24)
    out_of_service_cost: float = 2000.0  # EUR fixed cost of full replacement/repair

    # Scenario 3 – logistics center (hub)
    hub_city: str = "Frankfurt"
    hub_via_rate: float = 0.3  # fraction of new orders routed via hub

    # Scenario 4 – random road events
    event_interval_mean: float = 12.0  # mean hours between events
    event_weather_mult: float = 3.0  # speed multiplier for weather slowdown
    event_accident_mult: float = 6.0  # speed multiplier for accident
    event_weather_duration_mean: float = 4.0
    event_accident_duration_mean: float = 2.0
    event_closure_duration_mean: float = 10.0
