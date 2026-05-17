import tkinter as tk

from config import SimConfig
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
)

if __name__ == "__main__":
    root = tk.Tk()
    app = TransportApp(root, cfg)
    root.mainloop()
