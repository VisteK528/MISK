import time

from config import SimConfig
from engine import SimulationEngine

cfg = SimConfig(
    num_vehicles=8,
    vehicle_capacity=20000,
    vehicle_speed=80,
    fuel_cost_per_km=1.5,
    order_interval_mean=3.0,
    penalty_per_hour=50,
    simulation_duration=168,
    double_crew=False,
    scenario_breakdowns=False,
    scenario_logistics_center=False,
    scenario_random_events=False,
)

app = SimulationEngine(cfg)

real_time_dt = 0.01
while True:
    dt = app.config.time_step
    app.step(dt)
    for msg in app.log_messages:
        print(msg)
    time.sleep(real_time_dt)
    if app.time >= app.config.simulation_duration:
        break
