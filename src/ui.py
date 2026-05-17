import datetime
import json
import random
import tkinter as tk
from tkinter import filedialog, ttk

try:
    import matplotlib

    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

    _MPL = True
except ImportError:
    _MPL = False

from models import VehicleStatus, OrderStatus
from config import SimConfig
from engine import SimulationEngine

# ── Colour palette (dark theme) ───────────────────────────────────────────────
BG_DARK = "#1e1e2e"
BG_PANEL = "#24273a"
BG_SECTION = "#363a4f"
FG_TEXT = "#cad3f5"
FG_MUTED = "#8087a2"
ACCENT = "#8aadf4"
C_MOVING = "#a6da95"
C_IDLE = "#8aadf4"
C_RESTING = "#f5a97f"
C_BROKEN = "#ed8796"
C_ROAD = "#494d64"
C_ROAD_SLOW = "#eed49f"
C_ROAD_BLOCK = "#ed8796"
C_HUB = "#eed49f"
MAP_BG = "#181926"

_STATUS_COLOR = {
    VehicleStatus.MOVING: C_MOVING,
    VehicleStatus.IDLE: C_IDLE,
    VehicleStatus.RESTING: C_RESTING,
    VehicleStatus.BROKEN_DOWN: C_BROKEN,
}

_STATUS_NAME = {
    VehicleStatus.MOVING: "W trasie",
    VehicleStatus.IDLE: "Bezczynny",
    VehicleStatus.RESTING: "Odpoczynek",
    VehicleStatus.BROKEN_DOWN: "Awaria",
}


class TransportApp:
    def __init__(self, root, cfg: SimConfig):
        self.root = root
        self.engine = None  # created in _start_simulation
        self.cfg = cfg  # used to pre-fill the config screen

        self.root.title("System Logistyczny EU – Symulator")
        self.root.configure(bg=BG_DARK)
        self.root.geometry("1560x920")
        self.root.minsize(1100, 650)

        self.is_running = False
        self.speed_mult = 1.0
        self._finance_history: list[tuple] = []
        self._plot_counter = 0

        self._show_config_screen()

    # ══════════════════════════════════════════ PROJECTION ════════════

    def _init_projection(self):
        cities = self.engine.graph.cities
        lats = [v[0] for v in cities.values()]
        lons = [v[1] for v in cities.values()]
        self._min_lat, self._max_lat = min(lats), max(lats)
        self._min_lon, self._max_lon = min(lons), max(lons)

    # ══════════════════════════════════════════ CONFIG SCREEN ══════════

    def _show_config_screen(self):
        self._cfg_frame = tk.Frame(self.root, bg=BG_DARK)
        self._cfg_frame.pack(fill=tk.BOTH, expand=True)

        hdr = tk.Frame(self._cfg_frame, bg=BG_DARK, pady=14)
        hdr.pack(fill=tk.X)
        tk.Label(
            hdr,
            text="System Logistyczny EU",
            font=("Arial", 20, "bold"),
            bg=BG_DARK,
            fg=ACCENT,
        ).pack()
        tk.Label(
            hdr,
            text="Ustaw parametry symulacji i kliknij przycisk, aby uruchomić",
            font=("Arial", 10),
            bg=BG_DARK,
            fg=FG_MUTED,
        ).pack(pady=(4, 0))

        sc_wrap = tk.Frame(self._cfg_frame, bg=BG_DARK)
        sc_wrap.pack(fill=tk.BOTH, expand=True, padx=30, pady=4)

        sc = tk.Canvas(sc_wrap, bg=BG_DARK, highlightthickness=0)
        sb = ttk.Scrollbar(sc_wrap, orient=tk.VERTICAL, command=sc.yview)
        cfg_inner = tk.Frame(sc, bg=BG_DARK)

        cfg_inner.bind(
            "<Configure>", lambda e: sc.configure(scrollregion=sc.bbox("all"))
        )
        sc.create_window((0, 0), window=cfg_inner, anchor="nw")
        sc.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sc.bind_all(
            "<MouseWheel>", lambda e: sc.yview_scroll(int(-1 * e.delta / 120), "units")
        )

        left = tk.Frame(cfg_inner, bg=BG_DARK)
        middle = tk.Frame(cfg_inner, bg=BG_DARK)
        right = tk.Frame(cfg_inner, bg=BG_DARK)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        middle.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 6))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        self._p = {}
        c = self.cfg  # shorthand for defaults

        # ── helpers ───────────────────────────────────────────────────
        def section(parent, title):
            f = tk.Frame(parent, bg=BG_SECTION)
            f.pack(fill=tk.X, pady=(10, 3))
            tk.Label(
                f,
                text=f"  {title}",
                bg=BG_SECTION,
                fg=ACCENT,
                font=("Arial", 10, "bold"),
                pady=6,
            ).pack(side=tk.LEFT)

        def entry(parent, key, label, default, cast=float, w=32):
            row = tk.Frame(parent, bg=BG_PANEL)
            row.pack(fill=tk.X, padx=4, pady=2)
            tk.Label(
                row,
                text=label + ":",
                bg=BG_PANEL,
                fg=FG_MUTED,
                font=("Arial", 9),
                width=w,
                anchor="w",
            ).pack(side=tk.LEFT, padx=(8, 0))
            var = tk.StringVar(value=str(default))
            tk.Entry(
                row,
                textvariable=var,
                bg=BG_SECTION,
                fg=FG_TEXT,
                font=("Arial", 9),
                relief=tk.FLAT,
                bd=4,
                width=12,
                insertbackground=FG_TEXT,
            ).pack(side=tk.LEFT, padx=(6, 8), pady=4)
            self._p[key] = (var, cast)

        def sub_entry(parent, key, label, default, cast=float):
            row = tk.Frame(parent, bg=BG_DARK)
            row.pack(fill=tk.X, padx=4, pady=1)
            tk.Label(
                row,
                text="    " + label + ":",
                bg=BG_DARK,
                fg=FG_MUTED,
                font=("Arial", 8),
                width=36,
                anchor="w",
            ).pack(side=tk.LEFT, padx=(8, 0))
            var = tk.StringVar(value=str(default))
            tk.Entry(
                row,
                textvariable=var,
                bg=BG_SECTION,
                fg=FG_TEXT,
                font=("Arial", 8),
                relief=tk.FLAT,
                bd=3,
                width=10,
                insertbackground=FG_TEXT,
            ).pack(side=tk.LEFT, padx=(4, 8), pady=2)
            self._p[key] = (var, cast)

        def check(parent, key, label, default):
            row = tk.Frame(parent, bg=BG_PANEL)
            row.pack(fill=tk.X, padx=4, pady=2)
            var = tk.BooleanVar(value=default)
            tk.Checkbutton(
                row,
                text=f"  {label}",
                variable=var,
                bg=BG_PANEL,
                fg=FG_TEXT,
                selectcolor=BG_SECTION,
                activebackground=BG_PANEL,
                activeforeground=FG_TEXT,
                font=("Arial", 9),
                anchor="w",
            ).pack(side=tk.LEFT, fill=tk.X, padx=8, pady=4)
            self._p[key] = (var, bool)

        # ── Left: Fleet ───────────────────────────────────────────────
        section(left, "FLOTA")
        entry(left, "num_vehicles", "Liczba pojazdow", c.num_vehicles, int)
        entry(
            left,
            "vehicle_capacity",
            "Ladownosc pojazdu (kg)",
            c.vehicle_capacity,
            float,
        )
        entry(left, "vehicle_speed", "Predkosc pojazdu (km/h)", c.vehicle_speed, float)
        entry(
            left, "fuel_cost_per_km", "Koszt paliwa (EUR/km)", c.fuel_cost_per_km, float
        )
        entry(
            left,
            "max_driver_hours",
            "Maks. czas jazdy kierowcy (h)",
            c.max_driver_hours,
            float,
        )
        entry(
            left,
            "rest_duration",
            "Czas obowiazkowego odpoczynku (h)",
            c.rest_duration,
            float,
        )
        check(left, "double_crew", "Podwojna zaloga (bez odpoczynku)", c.double_crew)

        # ── Left: Simulation ──────────────────────────────────────────
        section(left, "SYMULACJA")
        entry(
            left,
            "simulation_duration",
            "Czas trwania symulacji (h)",
            c.simulation_duration,
            float,
        )
        entry(left, "time_step", "Krok czasowy (h)", c.time_step, float)

        # seed row: entry + "losowy" checkbox side-by-side
        seed_row = tk.Frame(left, bg=BG_PANEL)
        seed_row.pack(fill=tk.X, padx=4, pady=2)
        tk.Label(
            seed_row,
            text="Ziarno losowosci (seed):",
            bg=BG_PANEL,
            fg=FG_MUTED,
            font=("Arial", 9),
            width=32,
            anchor="w",
        ).pack(side=tk.LEFT, padx=(8, 0))
        self._seed_var = tk.StringVar(value=str(c.seed))
        self._seed_entry = tk.Entry(
            seed_row,
            textvariable=self._seed_var,
            bg=BG_SECTION,
            fg=FG_TEXT,
            font=("Arial", 9),
            relief=tk.FLAT,
            bd=4,
            width=8,
            insertbackground=FG_TEXT,
        )
        self._seed_entry.pack(side=tk.LEFT, padx=(6, 4), pady=4)
        self._seed_random = tk.BooleanVar(value=False)

        def _toggle_seed_entry(*_):
            self._seed_entry.config(
                state=tk.DISABLED if self._seed_random.get() else tk.NORMAL,
                fg=FG_MUTED if self._seed_random.get() else FG_TEXT,
            )

        self._seed_random.trace_add("write", _toggle_seed_entry)
        tk.Checkbutton(
            seed_row,
            text="losowy",
            variable=self._seed_random,
            bg=BG_PANEL,
            fg=FG_MUTED,
            selectcolor=BG_SECTION,
            activebackground=BG_PANEL,
            activeforeground=FG_TEXT,
            font=("Arial", 8),
        ).pack(side=tk.LEFT)

        # ── Middle: Orders ────────────────────────────────────────────
        section(middle, "ZLECENIA")
        entry(
            middle,
            "order_interval_mean",
            "Sredni interwal zlecen (h)",
            c.order_interval_mean,
            float,
        )
        entry(
            middle,
            "order_weight_min",
            "Min. waga zlecenia (kg)",
            c.order_weight_min,
            float,
        )
        entry(
            middle,
            "order_weight_max",
            "Maks. waga zlecenia (kg)",
            c.order_weight_max,
            float,
        )
        entry(
            middle,
            "order_deadline_min",
            "Min. termin dostawy (h)",
            c.order_deadline_min,
            float,
        )
        entry(
            middle,
            "order_deadline_max",
            "Maks. termin dostawy (h)",
            c.order_deadline_max,
            float,
        )
        entry(
            middle,
            "penalty_per_hour",
            "Kara za opoznienie (EUR/h)",
            c.penalty_per_hour,
            float,
        )
        entry(
            middle,
            "base_revenue",
            "Bazowy przychod za zlecenie (EUR)",
            c.base_revenue,
            float,
        )
        entry(
            middle,
            "revenue_per_km",
            "Przychod za km trasy (EUR/km)",
            c.revenue_per_km,
            float,
        )

        # ── Right: Scenarios ──────────────────────────────────────────
        section(right, "SCENARIUSZE")

        check(
            right,
            "scenario_breakdowns",
            "Awarie pojazdow (Scenariusz 2)",
            c.scenario_breakdowns,
        )
        sub_entry(right, "breakdown_k", "Liczba pojazdow do awarii", c.breakdown_k, int)
        sub_entry(
            right,
            "breakdown_trigger_time",
            "Czas wyzwolenia awarii (h)",
            c.breakdown_trigger_time,
            float,
        )
        sub_entry(
            right,
            "repair_driver_prob",
            "Prawd. naprawy wlasnej (0-1)",
            c.repair_driver_prob,
            float,
        )
        sub_entry(
            right,
            "repair_mobile_prob",
            "Prawd. serwisu mobilnego (0-1)",
            c.repair_mobile_prob,
            float,
        )
        sub_entry(
            right,
            "repair_driver_delay",
            "Opoznienie – naprawa wlasna (h)",
            c.repair_driver_delay,
            float,
        )
        sub_entry(
            right,
            "mobile_service_delay",
            "Opoznienie – serwis mobilny (h)",
            c.mobile_service_delay,
            float,
        )
        sub_entry(
            right,
            "mobile_service_cost",
            "Koszt serwisu mobilnego (EUR)",
            c.mobile_service_cost,
            float,
        )
        sub_entry(
            right,
            "out_of_service_duration",
            "Czas wylaczenia pojazdu (h)",
            c.out_of_service_duration,
            float,
        )
        sub_entry(
            right,
            "out_of_service_cost",
            "Koszt wylaczenia pojazdu (EUR)",
            c.out_of_service_cost,
            float,
        )

        check(
            right,
            "scenario_logistics_center",
            "Centrum logistyczne (Scenariusz 3)",
            c.scenario_logistics_center,
        )
        sub_entry(right, "hub_city", "Miasto centralne (hub)", c.hub_city, str)
        sub_entry(
            right,
            "hub_via_rate",
            "Udzial zlecen przez hub (0–1)",
            c.hub_via_rate,
            float,
        )

        check(
            right,
            "scenario_random_events",
            "Losowe utrudnienia drogowe (Scenariusz 4)",
            c.scenario_random_events,
        )
        sub_entry(
            right,
            "event_interval_mean",
            "Sredni interwal zdarzen (h)",
            c.event_interval_mean,
            float,
        )
        sub_entry(
            right,
            "event_weather_mult",
            "Mnoznik spowolnienia – pogoda",
            c.event_weather_mult,
            float,
        )
        sub_entry(
            right,
            "event_accident_mult",
            "Mnoznik spowolnienia – wypadek",
            c.event_accident_mult,
            float,
        )
        sub_entry(
            right,
            "event_weather_duration_mean",
            "Sredni czas zdarz. pogodowego (h)",
            c.event_weather_duration_mean,
            float,
        )
        sub_entry(
            right,
            "event_accident_duration_mean",
            "Sredni czas wypadku (h)",
            c.event_accident_duration_mean,
            float,
        )
        sub_entry(
            right,
            "event_closure_duration_mean",
            "Sredni czas zamkniecia drogi (h)",
            c.event_closure_duration_mean,
            float,
        )

        # ── Run button ────────────────────────────────────────────────
        btn_wrap = tk.Frame(self._cfg_frame, bg=BG_DARK, pady=18)
        btn_wrap.pack()
        tk.Button(
            btn_wrap,
            text="     Uruchom Symulacje     ",
            font=("Arial", 13, "bold"),
            bg=C_MOVING,
            fg=BG_DARK,
            relief=tk.FLAT,
            padx=20,
            pady=12,
            cursor="hand2",
            command=self._start_simulation,
        ).pack()

    def _start_simulation(self):
        params = {}
        for key, (var, cast) in self._p.items():
            try:
                params[key] = var.get() if cast is bool else cast(var.get())
            except (ValueError, TypeError):
                pass

        if self._seed_random.get():
            params["seed"] = random.randint(0, 2**31 - 1)
        else:
            try:
                params["seed"] = int(self._seed_var.get())
            except ValueError:
                params["seed"] = 42

        cfg = SimConfig(**params)
        self.engine = SimulationEngine(cfg)
        self.cfg = cfg

        self._finance_history = []
        self._plot_counter = 0
        self.speed_mult = 1.0

        self._cfg_frame.destroy()
        self._init_projection()
        self._setup_ui()

    # ══════════════════════════════════════════ UI CONSTRUCTION ════════

    def _setup_ui(self):
        self._sim_frame = tk.Frame(self.root, bg=BG_DARK)
        self._sim_frame.pack(fill=tk.BOTH, expand=True)
        self._build_topbar()
        self._build_main_area()

    def _build_topbar(self):
        bar = tk.Frame(self._sim_frame, bg=BG_DARK, pady=8)
        bar.pack(fill=tk.X)

        tk.Label(
            bar,
            text="System Logistyczny EU",
            font=("Arial", 15, "bold"),
            bg=BG_DARK,
            fg=ACCENT,
        ).pack(side=tk.LEFT, padx=14)

        self.lbl_time = tk.Label(
            bar, text="Czas: 0.0 h", font=("Arial", 13), bg=BG_DARK, fg=FG_TEXT
        )
        self.lbl_time.pack(side=tk.LEFT, padx=20)

        ctrl = tk.Frame(bar, bg=BG_DARK)
        ctrl.pack(side=tk.RIGHT, padx=14)
        self._topbar_ctrl = ctrl

        self.btn_toggle = tk.Button(
            ctrl,
            text="  START",
            font=("Arial", 11, "bold"),
            bg=C_MOVING,
            fg=BG_DARK,
            relief=tk.FLAT,
            padx=14,
            pady=5,
            cursor="hand2",
            command=self._toggle_sim,
        )
        self.btn_toggle.pack(side=tk.LEFT, padx=6)

        tk.Label(
            ctrl, text="Predkosc:", bg=BG_DARK, fg=FG_MUTED, font=("Arial", 10)
        ).pack(side=tk.LEFT, padx=(14, 0))

        self.speed_var = tk.DoubleVar(value=1.0)
        tk.Scale(
            ctrl,
            from_=0.5,
            to=10.0,
            resolution=0.5,
            orient=tk.HORIZONTAL,
            length=170,
            variable=self.speed_var,
            bg=BG_DARK,
            fg=FG_TEXT,
            troughcolor=BG_SECTION,
            highlightthickness=0,
            bd=0,
            command=self._on_speed,
        ).pack(side=tk.LEFT)

        self.lbl_speed = tk.Label(
            ctrl,
            text="1.0x",
            width=5,
            bg=BG_DARK,
            fg=ACCENT,
            font=("Arial", 10, "bold"),
        )
        self.lbl_speed.pack(side=tk.LEFT, padx=4)

    def _build_main_area(self):
        main = tk.Frame(self._sim_frame, bg=BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        map_wrap = tk.Frame(main, bg=MAP_BG, bd=1, relief=tk.SUNKEN)
        map_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(map_wrap, bg=MAP_BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_resize)

        panel = tk.Frame(main, bg=BG_PANEL, width=410)
        panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        panel.pack_propagate(False)
        self._build_stats_panel(panel)

    def _build_stats_panel(self, parent):
        sc = tk.Canvas(parent, bg=BG_PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=sc.yview)
        self._sf = tk.Frame(sc, bg=BG_PANEL)

        self._sf.bind(
            "<Configure>", lambda e: sc.configure(scrollregion=sc.bbox("all"))
        )
        sc.create_window((0, 0), window=self._sf, anchor="nw")
        sc.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sc.bind_all(
            "<MouseWheel>", lambda e: sc.yview_scroll(int(-1 * e.delta / 120), "units")
        )

        sf = self._sf

        # ── Simulation overview ───────────────────────────────────────
        self._sec(sf, "SYMULACJA")
        self._sim = {}
        self._sim["progress"] = self._row(sf, "Postep symulacji", "—")
        self._sim["scenario"] = self._row(sf, "Scenariusz", "Bazowy")
        self._sim["breakdowns"] = self._row(sf, "Awarie (zdarzenia)", "0", C_BROKEN)
        self._sim["road_events"] = self._row(
            sf, "Utrudnienia akt./lacznie", "0 / 0", C_ROAD_SLOW
        )
        self._sim["hub_waiting"] = self._row(sf, "Ladunek w hubie", "0", C_HUB)
        self._sim["hub_delivered"] = self._row(sf, "Dost. przez hub", "0", C_HUB)

        # ── Orders ───────────────────────────────────────────────────
        self._sec(sf, "ZLECENIA")
        self._ord = {}
        for k, name, col in [
            ("total", "Wszystkie", FG_TEXT),
            ("pending", "Oczekujace", C_RESTING),
            ("in_transit", "W transporcie", C_IDLE),
            ("at_hub", "W hubie", C_HUB),
            ("delivered", "Dostarczone", C_MOVING),
            ("on_time", "  Na czas", C_MOVING),
            ("late", "  Spoznione", C_BROKEN),
        ]:
            self._ord[k] = self._row(sf, name, "0", col)

        # ── Finance ──────────────────────────────────────────────────
        self._sec(sf, "FINANSE (EUR)")
        self._fin = {}
        self._fin["revenue"] = self._row(sf, "Przychod", "EUR 0", C_MOVING)

        ttk.Separator(sf, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=3)

        self._fin["fuel"] = self._row(sf, "Koszt paliwa", "EUR 0", FG_TEXT)
        self._fin["penalty"] = self._row(sf, "Kary (opoznienia)", "EUR 0", C_BROKEN)
        self._fin["repair"] = self._row(sf, "Koszty napraw", "EUR 0", C_RESTING)

        ttk.Separator(sf, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=3)

        self._fin["total"] = self._row(sf, "Koszty lacznie", "EUR 0", ACCENT, bold=True)

        ttk.Separator(sf, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=5)

        self._fin["profit"] = self._row(sf, "ZYSK NETTO", "EUR 0", C_MOVING, bold=True)

        # ── Finance plot ──────────────────────────────────────────────
        self._sec(sf, "WYKRES FINANSOWY")
        self._build_finance_plot(sf)

        # ── Fleet summary ─────────────────────────────────────────────
        self._sec(sf, "FLOTA")
        self._fleet = {}
        for k, name, col in [
            ("moving", "W trasie", C_MOVING),
            ("idle", "Bezczynne", C_IDLE),
            ("resting", "Odpoczynek", C_RESTING),
            ("broken", "Awaria", C_BROKEN),
        ]:
            row = tk.Frame(sf, bg=BG_PANEL)
            row.pack(fill=tk.X, padx=10, pady=1)
            tk.Label(
                row, text="o", bg=BG_PANEL, fg=col, font=("Arial", 12, "bold")
            ).pack(side=tk.LEFT)
            tk.Label(
                row,
                text=f"  {name}:",
                bg=BG_PANEL,
                fg=FG_MUTED,
                font=("Arial", 9),
                width=14,
                anchor="w",
            ).pack(side=tk.LEFT)
            lbl = tk.Label(
                row, text="0", bg=BG_PANEL, fg=col, font=("Arial", 9, "bold")
            )
            lbl.pack(side=tk.LEFT)
            self._fleet[k] = lbl

        # ── Per-vehicle table ─────────────────────────────────────────
        self._sec(sf, "POJAZDY – SZCZEGOLY")
        self._build_vehicle_table(sf)

        # ── Map legend ────────────────────────────────────────────────
        self._sec(sf, "LEGENDA MAPY")
        leg = tk.Frame(sf, bg=BG_PANEL)
        leg.pack(fill=tk.X, padx=10, pady=4)
        for col, txt in [
            (C_MOVING, "Pojazd – jedzie"),
            (C_IDLE, "Pojazd – bezczynny"),
            (C_RESTING, "Pojazd – odpoczynek kierowcy"),
            (C_BROKEN, "Pojazd – awaria"),
            (C_HUB, "Centrum logistyczne"),
            (C_ROAD_SLOW, "Droga z utrudnieniami"),
            (C_ROAD_BLOCK, "Droga zablokowana"),
        ]:
            r = tk.Frame(leg, bg=BG_PANEL)
            r.pack(fill=tk.X, pady=1)
            tk.Label(r, text="o", bg=BG_PANEL, fg=col, font=("Arial", 10, "bold")).pack(
                side=tk.LEFT
            )
            tk.Label(
                r, text=f"  {txt}", bg=BG_PANEL, fg=FG_MUTED, font=("Arial", 8)
            ).pack(side=tk.LEFT)

        # ── Event log ─────────────────────────────────────────────────
        self._sec(sf, "LOG ZDARZEN")
        lw = tk.Frame(sf, bg=BG_PANEL)
        lw.pack(fill=tk.X, padx=6, pady=4)

        self._log = tk.Text(
            lw,
            height=14,
            bg=BG_SECTION,
            fg=FG_TEXT,
            font=("Courier", 8),
            wrap=tk.WORD,
            bd=0,
            insertbackground=FG_TEXT,
            state=tk.DISABLED,
        )
        lsb = ttk.Scrollbar(lw, orient=tk.VERTICAL, command=self._log.yview)
        self._log.configure(yscrollcommand=lsb.set)
        lsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._log.tag_configure("delivery", foreground=C_MOVING)
        self._log.tag_configure("order", foreground=ACCENT)
        self._log.tag_configure("rest", foreground=C_RESTING)
        self._log.tag_configure("error", foreground=C_BROKEN)
        self._log.tag_configure("hub", foreground=C_HUB)
        self._log.tag_configure("road", foreground=C_ROAD_SLOW)

    def _build_vehicle_table(self, parent):
        wrap = tk.Frame(parent, bg=BG_PANEL)
        wrap.pack(fill=tk.X, padx=6, pady=4)

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "V.Treeview",
            background=BG_SECTION,
            foreground=FG_TEXT,
            fieldbackground=BG_SECTION,
            rowheight=22,
            font=("Arial", 8),
        )
        style.configure(
            "V.Treeview.Heading",
            background=BG_DARK,
            foreground=ACCENT,
            font=("Arial", 8, "bold"),
            relief="flat",
        )
        style.map("V.Treeview", background=[("selected", "#45475a")])

        cols = ("id", "status", "city", "load", "del", "fuel")
        n = len(self.engine.vehicles)
        self._tree = ttk.Treeview(
            wrap, columns=cols, show="headings", height=min(n, 10), style="V.Treeview"
        )
        for col, w, lbl in [
            ("id", 30, "#"),
            ("status", 80, "Status"),
            ("city", 85, "Miasto"),
            ("load", 55, "Ladunek"),
            ("del", 40, "Dost."),
            ("fuel", 70, "Paliwo EUR"),
        ]:
            self._tree.heading(col, text=lbl)
            self._tree.column(col, width=w, anchor="center")

        vsb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(side=tk.LEFT, fill=tk.X, expand=True)

        for status, col in _STATUS_COLOR.items():
            self._tree.tag_configure(status.value, foreground=col)

    def _build_finance_plot(self, parent):
        plot_frame = tk.Frame(parent, bg=BG_PANEL)
        plot_frame.pack(fill=tk.X, padx=6, pady=4)

        if not _MPL:
            tk.Label(
                plot_frame,
                text="(matplotlib nie jest zainstalowany)",
                bg=BG_PANEL,
                fg=FG_MUTED,
                font=("Arial", 8),
            ).pack()
            self._plot_ax = None
            self._plot_canvas = None
            return

        fig = Figure(figsize=(3.8, 2.1), dpi=90, facecolor=BG_SECTION)
        fig.subplots_adjust(left=0.05, right=0.65, top=0.93, bottom=0.22)
        ax = fig.add_subplot(111)
        ax.set_facecolor(BG_PANEL)
        ax.tick_params(colors=FG_MUTED, labelsize=6)
        ax.set_xlabel("Czas [h]", color=FG_MUTED, fontsize=6)
        ax.set_ylabel("EUR", color=FG_MUTED, fontsize=6)
        ax.axhline(0, color=FG_MUTED, linewidth=0.5, linestyle="--", alpha=0.5)
        for spine in ax.spines.values():
            spine.set_color(BG_SECTION)
        ax.grid(True, color=FG_MUTED, alpha=0.15, linewidth=0.5)

        self._plot_ax = ax
        self._plot_fig = fig

        canvas = FigureCanvasTkAgg(fig, master=plot_frame)
        canvas.get_tk_widget().configure(bg=BG_PANEL, highlightthickness=0)
        canvas.get_tk_widget().pack(fill=tk.X)
        self._plot_canvas = canvas

    # ══════════════════════════════════════════ HELPERS ════════════════

    def _sec(self, parent, title: str):
        f = tk.Frame(parent, bg=BG_SECTION)
        f.pack(fill=tk.X, pady=(8, 2))
        tk.Label(
            f,
            text=f"  {title}",
            bg=BG_SECTION,
            fg=ACCENT,
            font=("Arial", 9, "bold"),
            pady=4,
        ).pack(side=tk.LEFT)

    def _row(
        self, parent, label: str, default: str, color: str = FG_TEXT, bold: bool = False
    ) -> tk.Label:
        row = tk.Frame(parent, bg=BG_PANEL)
        row.pack(fill=tk.X, padx=10, pady=1)
        tk.Label(
            row,
            text=label + ":",
            bg=BG_PANEL,
            fg=FG_MUTED,
            font=("Arial", 9),
            width=22,
            anchor="w",
        ).pack(side=tk.LEFT)
        lbl = tk.Label(
            row,
            text=default,
            bg=BG_PANEL,
            fg=color,
            font=("Arial", 9, "bold" if bold else "normal"),
            anchor="w",
        )
        lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return lbl

    def _on_resize(self, _event=None):
        self.canvas.delete("road")
        self.canvas.delete("static")
        self._draw_roads()
        self._draw_static_map()

    def _on_speed(self, _val=None):
        self.speed_mult = self.speed_var.get()
        self.lbl_speed.config(text=f"{self.speed_mult:.1f}x")

    def _xy(self, lat: float, lon: float):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        px, py = 60, 40
        x = px + (lon - self._min_lon) / (self._max_lon - self._min_lon) * (w - 2 * px)
        y = (
            h
            - py
            - (lat - self._min_lat) / (self._max_lat - self._min_lat) * (h - 2 * py)
        )
        return x, y

    # ══════════════════════════════════════════ MAP DRAWING ════════════

    def _draw_static_map(self):
        g = self.engine.graph
        hub_city = self.cfg.hub_city if self.cfg.scenario_logistics_center else None
        for name, (lat, lon) in g.cities.items():
            x, y = self._xy(lat, lon)
            is_hub = name == hub_city
            r = 7 if is_hub else 4
            fill = C_HUB if is_hub else FG_TEXT
            outl = C_HUB if is_hub else BG_DARK
            self.canvas.create_oval(
                x - r,
                y - r,
                x + r,
                y + r,
                fill=fill,
                outline=outl,
                width=1.5,
                tags="static",
            )
            self.canvas.create_text(
                x, y - r - 6, text=name, fill=fill, font=("Arial", 7), tags="static"
            )
            if is_hub:
                self.canvas.create_text(
                    x,
                    y - r - 18,
                    text="CENTRUM LOGISTYCZNE",
                    fill=C_HUB,
                    font=("Arial", 7, "bold"),
                    tags="static",
                )

    def _draw_roads(self):
        self.canvas.delete("road")
        g = self.engine.graph
        for c1, c2 in g.get_all_road_keys():
            lat1, lon1 = g.cities[c1]
            lat2, lon2 = g.cities[c2]
            x1, y1 = self._xy(lat1, lon1)
            x2, y2 = self._xy(lat2, lon2)
            mult = g.get_multiplier(c1, c2)
            if mult >= 100:
                color, dash, w = C_ROAD_BLOCK, (4, 4), 2.5
            elif mult > 1.2:
                color, dash, w = C_ROAD_SLOW, (6, 3), 2.0
            else:
                color, dash, w = C_ROAD, (), 1.5
            self.canvas.create_line(
                x1, y1, x2, y2, fill=color, width=w, dash=dash, tags="road"
            )
            # Event markers at road midpoint
            if mult >= 100:
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                s = 6
                self.canvas.create_line(
                    mx - s,
                    my - s,
                    mx + s,
                    my + s,
                    fill=C_ROAD_BLOCK,
                    width=2.5,
                    tags="road",
                )
                self.canvas.create_line(
                    mx + s,
                    my - s,
                    mx - s,
                    my + s,
                    fill=C_ROAD_BLOCK,
                    width=2.5,
                    tags="road",
                )
            elif mult > 1.2:
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                self.canvas.create_oval(
                    mx - 6,
                    my - 6,
                    mx + 6,
                    my + 6,
                    fill=BG_DARK,
                    outline=C_ROAD_SLOW,
                    width=1.5,
                    tags="road",
                )
                self.canvas.create_text(
                    mx,
                    my,
                    text="!",
                    fill=C_ROAD_SLOW,
                    font=("Arial", 9, "bold"),
                    tags="road",
                )
        # Roads must stay behind city dots and routes
        self.canvas.tag_lower("road")

    def _draw_routes(self):
        self.canvas.delete("route")
        for v in self.engine.vehicles:
            if v.status != VehicleStatus.MOVING:
                continue
            if len(v.route) <= v.route_index + 1:
                continue
            color = _STATUS_COLOR[v.status]
            lat0, lon0 = self.engine.get_vehicle_position(v)
            pts = list(self._xy(lat0, lon0))
            for i in range(v.route_index + 1, len(v.route)):
                lat2, lon2 = self.engine.graph.cities[v.route[i]]
                pts += list(self._xy(lat2, lon2))
            if len(pts) >= 4:
                self.canvas.create_line(
                    *pts, fill=color, width=1.5, dash=(5, 3), tags="route"
                )

    def _draw_vehicles(self):
        self.canvas.delete("vehicle")
        for v in self.engine.vehicles:
            lat, lon = self.engine.get_vehicle_position(v)
            x, y = self._xy(lat, lon)
            col = _STATUS_COLOR.get(v.status, C_IDLE)

            self.canvas.create_oval(
                x - 11,
                y - 11,
                x + 11,
                y + 11,
                fill="",
                outline=col,
                width=1,
                tags="vehicle",
            )
            self.canvas.create_oval(
                x - 7,
                y - 7,
                x + 7,
                y + 7,
                fill=col,
                outline=BG_DARK,
                width=1.5,
                tags="vehicle",
            )
            self.canvas.create_text(
                x,
                y,
                text=str(v.id),
                fill=BG_DARK,
                font=("Arial", 7, "bold"),
                tags="vehicle",
            )
            if v.status == VehicleStatus.BROKEN_DOWN:
                # Dashed outer warning ring
                self.canvas.create_oval(
                    x - 15,
                    y - 15,
                    x + 15,
                    y + 15,
                    fill="",
                    outline=C_BROKEN,
                    width=2,
                    dash=(3, 3),
                    tags="vehicle",
                )
                # X cross drawn over the vehicle body
                self.canvas.create_line(
                    x - 5, y - 5, x + 5, y + 5, fill=BG_DARK, width=2.5, tags="vehicle"
                )
                self.canvas.create_line(
                    x + 5, y - 5, x - 5, y + 5, fill=BG_DARK, width=2.5, tags="vehicle"
                )

    # ══════════════════════════════════════════ SIMULATION LOOP ════════

    def _restart(self):
        self.is_running = False
        self._sim_frame.destroy()
        self._finance_history = []
        self._plot_counter = 0
        self._show_config_screen()

    def _export_sim(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialfile=f"sim_{ts}.json",
            title="Eksportuj dane symulacji",
        )
        if not path:
            return

        data = self.engine.export_data()

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _toggle_sim(self):
        if not self.is_running:
            self.is_running = True
            self.btn_toggle.config(text="  PAUZA", bg=C_RESTING)
            self._run()
        else:
            self.is_running = False
            self.btn_toggle.config(text="  START", bg=C_MOVING)

    def _run(self):
        if not self.is_running:
            return

        dt = self.cfg.time_step * self.speed_mult
        self.engine.step(dt)

        self.lbl_time.config(text=f"Czas: {self.engine.time:.1f} h")
        self._draw_roads()
        self._draw_routes()
        self._draw_vehicles()
        self._update_stats()
        self._drain_log()

        self._plot_counter += 1
        if self._plot_counter % 20 == 0:
            self._redraw_plot()

        if self.engine.time < self.cfg.simulation_duration:
            self.root.after(30, self._run)
        else:
            self._redraw_plot()
            self.is_running = False
            self.btn_toggle.config(text="  KONIEC", bg=C_IDLE, state=tk.DISABLED)
            tk.Button(
                self._topbar_ctrl,
                text="  Uruchom ponownie",
                font=("Arial", 11, "bold"),
                bg=ACCENT,
                fg=BG_DARK,
                relief=tk.FLAT,
                padx=14,
                pady=5,
                cursor="hand2",
                command=self._restart,
            ).pack(side=tk.LEFT, padx=6)
            tk.Button(
                self._topbar_ctrl,
                text="  Eksportuj dane",
                font=("Arial", 11, "bold"),
                bg=C_RESTING,
                fg=BG_DARK,
                relief=tk.FLAT,
                padx=14,
                pady=5,
                cursor="hand2",
                command=self._export_sim,
            ).pack(side=tk.LEFT, padx=6)

    # ══════════════════════════════════════════ STATS UPDATE ═══════════

    def _update_stats(self):
        stats = self.engine.get_stats()

        # accumulate history for the plot
        self._finance_history.append(
            (
                stats["time"],
                stats["total_revenue"],
                stats["total_cost"],
                stats["net_profit"],
            )
        )

        # ── Simulation overview ───────────────────────────────────────
        pct = stats["time"] / self.cfg.simulation_duration * 100
        self._sim["progress"].config(
            text=f"{stats['time']:.1f} / {self.cfg.simulation_duration:.0f} h  ({pct:.0f}%)"
        )

        scen = []
        if self.cfg.scenario_breakdowns:
            scen.append("Awarie")
        if self.cfg.scenario_logistics_center:
            scen.append("Hub")
        if self.cfg.scenario_random_events:
            scen.append("Utrudnienia")
        self._sim["scenario"].config(text=", ".join(scen) or "Bazowy (S1)")

        self._sim["breakdowns"].config(text=str(stats["breakdown_events"]))
        self._sim["road_events"].config(
            text=f"{stats['active_road_events']} / {stats['road_events_total']}"
        )
        self._sim["hub_waiting"].config(text=str(stats["hub_at_hub"]))
        self._sim["hub_delivered"].config(text=str(stats["hub_via_delivered"]))

        # ── Orders ───────────────────────────────────────────────────
        in_tr = sum(
            1
            for o in self.engine.orders
            if o.status in (OrderStatus.ASSIGNED, OrderStatus.IN_TRANSIT)
        )
        self._ord["total"].config(text=str(stats["total_orders"]))
        self._ord["pending"].config(text=str(stats["pending"]))
        self._ord["in_transit"].config(text=str(in_tr))
        self._ord["at_hub"].config(text=str(stats["hub_at_hub"]))
        self._ord["delivered"].config(text=str(stats["delivered"]))
        self._ord["on_time"].config(text=str(stats["on_time"]))
        late_txt = str(stats["late"])
        if stats["late"]:
            late_txt += f"  ({stats['total_delay_h']:.0f}h)"
        self._ord["late"].config(text=late_txt)

        # ── Finance ──────────────────────────────────────────────────
        self._fin["revenue"].config(text=f"EUR {stats['total_revenue']:,.0f}")
        self._fin["fuel"].config(text=f"EUR {stats['total_fuel']:,.0f}")
        self._fin["penalty"].config(text=f"EUR {stats['total_penalty']:,.0f}")
        self._fin["repair"].config(text=f"EUR {stats['total_repair']:,.0f}")
        self._fin["total"].config(text=f"EUR {stats['total_cost']:,.0f}")

        profit = stats["net_profit"]
        self._fin["profit"].config(
            text=f"EUR {profit:,.0f}",
            fg=C_MOVING if profit >= 0 else C_BROKEN,
        )

        # ── Fleet ─────────────────────────────────────────────────────
        self._fleet["moving"].config(text=str(stats["vehicles_moving"]))
        self._fleet["idle"].config(text=str(stats["vehicles_idle"]))
        self._fleet["resting"].config(text=str(stats["vehicles_resting"]))
        self._fleet["broken"].config(text=str(stats["vehicles_broken"]))

        # ── Per-vehicle table ─────────────────────────────────────────
        for item in self._tree.get_children():
            self._tree.delete(item)
        for v in self.engine.vehicles:
            load_pct = (
                f"{v.current_load / v.capacity * 100:.0f}%" if v.capacity else "0%"
            )
            self._tree.insert(
                "",
                tk.END,
                values=(
                    v.id,
                    _STATUS_NAME.get(v.status, "?"),
                    v.current_city[:12],
                    load_pct,
                    v.deliveries,
                    f"{v.total_fuel_cost:,.0f}",
                ),
                tags=(v.status.value,),
            )

    def _redraw_plot(self):
        if not _MPL or self._plot_ax is None or len(self._finance_history) < 2:
            return

        history = self._finance_history
        # downsample if too many points
        if len(history) > 400:
            step = len(history) // 400 + 1
            history = history[::step]

        times = [p[0] for p in history]
        revenues = [p[1] for p in history]
        costs = [p[2] for p in history]
        profits = [p[3] for p in history]

        ax = self._plot_ax
        ax.clear()
        ax.set_facecolor(BG_PANEL)
        ax.tick_params(colors=FG_MUTED, labelsize=6)
        ax.set_xlabel("Czas [h]", color=FG_MUTED, fontsize=6)
        ax.set_ylabel("EUR", color=FG_MUTED, fontsize=6)
        for spine in ax.spines.values():
            spine.set_color(BG_SECTION)
        ax.grid(True, color=FG_MUTED, alpha=0.15, linewidth=0.5)
        ax.axhline(0, color=FG_MUTED, linewidth=0.6, linestyle="--", alpha=0.5)

        ax.plot(times, revenues, color=C_MOVING, linewidth=1.2, label="Przychod")
        ax.plot(times, costs, color=C_BROKEN, linewidth=1.2, label="Koszty lacznie")
        ax.plot(times, profits, color=ACCENT, linewidth=1.2, label="Zysk netto")

        ax.legend(
            fontsize=5.5,
            facecolor=BG_SECTION,
            edgecolor=FG_MUTED,
            labelcolor=FG_TEXT,
            loc="upper left",
            framealpha=0.8,
            handlelength=1.5,
        )

        self._plot_canvas.draw()

    # ══════════════════════════════════════════ LOG ════════════════════

    def _drain_log(self):
        if not self.engine.log_messages:
            return
        self._log.config(state=tk.NORMAL)
        while self.engine.log_messages:
            msg = self.engine.log_messages.popleft()
            self._log.insert(tk.END, msg + "\n", self._log_tag(msg))
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    @staticmethod
    def _log_tag(msg: str) -> str:
        m = msg.lower()
        if "delivered" in m or "dostarcz" in m:
            return "delivery"
        if "order" in m:
            return "order"
        if "resting" in m or "rested" in m:
            return "rest"
        if (
            "stuck" in m
            or "broken" in m
            or "repair" in m
            or "breakdown" in m
            or "awaria" in m
        ):
            return "error"
        if "hub" in m or "centrum" in m:
            return "hub"
        if "road" in m or "event" in m or "rerouted" in m or "cleared" in m:
            return "road"
        return ""
