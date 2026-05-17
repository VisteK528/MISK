import tkinter as tk
from config import SimConfig
from engine import SimulationEngine
from ui import TransportApp

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

app_engine = SimulationEngine(cfg)

if __name__ == "__main__":
    root = tk.Tk()
    # Przekazujemy zainicjalizowany silnik do UI
    app = TransportApp(root, app_engine)
    root.mainloop()
