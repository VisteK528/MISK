import tkinter as tk
from tkinter import ttk
from models import VehicleStatus, OrderStatus

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
    def __init__(self, root, engine):
        self.root = root
        self.engine = engine
        self.cfg = engine.config

        self.root.title("System Logistyczny EU – Symulator")
        self.root.configure(bg=BG_DARK)
        self.root.geometry("1560x920")
        self.root.minsize(1100, 650)

        self.is_running = False
        self.speed_mult = 1.0

        # Projection bounds
        cities = engine.graph.cities
        lats = [v[0] for v in cities.values()]
        lons = [v[1] for v in cities.values()]
        self._min_lat, self._max_lat = min(lats), max(lats)
        self._min_lon, self._max_lon = min(lons), max(lons)

        self._setup_ui()

    # ══════════════════════════════════════════ UI CONSTRUCTION ═══

    def _setup_ui(self):
        self._build_topbar()
        self._build_main_area()

    def _build_topbar(self):
        bar = tk.Frame(self.root, bg=BG_DARK, pady=8)
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
        main = tk.Frame(self.root, bg=BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Map (left, expands)
        map_wrap = tk.Frame(main, bg=MAP_BG, bd=1, relief=tk.SUNKEN)
        map_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(map_wrap, bg=MAP_BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_resize)

        # Stats panel (right, fixed width)
        panel = tk.Frame(main, bg=BG_PANEL, width=395)
        panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        panel.pack_propagate(False)
        self._build_stats_panel(panel)

    def _build_stats_panel(self, parent):
        sc = tk.Canvas(parent, bg=BG_PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=sc.yview)
        self._sf = tk.Frame(sc, bg=BG_PANEL)

        self._sf.bind(
            "<Configure>",
            lambda e: sc.configure(scrollregion=sc.bbox("all")),
        )
        sc.create_window((0, 0), window=self._sf, anchor="nw")
        sc.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        sc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sc.bind_all(
            "<MouseWheel>",
            lambda e: sc.yview_scroll(int(-1 * e.delta / 120), "units"),
        )

        sf = self._sf

        # ── Simulation progress ────────────────────────────────────
        self._sec(sf, "SYMULACJA")
        self._sim = {}
        self._sim["progress"] = self._row(sf, "Postep symulacji", "—")
        self._sim["scenario"] = self._row(sf, "Scenariusz", "Bazowy")

        # ── Orders ────────────────────────────────────────────────
        self._sec(sf, "ZLECENIA")
        self._ord = {}
        for k, name, col in [
            ("total", "Wszystkie", FG_TEXT),
            ("pending", "Oczekujace", C_RESTING),
            ("in_transit", "W transporcie", C_IDLE),
            ("delivered", "Dostarczone", C_MOVING),
            ("on_time", "  Na czas", C_MOVING),
            ("late", "  Spoznione", C_BROKEN),
        ]:
            self._ord[k] = self._row(sf, name, "0", col)

        # ── Costs ─────────────────────────────────────────────────
        self._sec(sf, "KOSZTY (EUR)")
        self._cost = {}
        for k, name, col in [
            ("fuel", "Paliwo", FG_TEXT),
            ("penalty", "Kary (opoznienia)", C_BROKEN),
            ("repair", "Naprawy", C_RESTING),
        ]:
            self._cost[k] = self._row(sf, name, "EUR 0", col)

        ttk.Separator(sf, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=4)
        self._cost["total"] = self._row(sf, "LACZNIE", "EUR 0", ACCENT, bold=True)

        # ── Fleet summary ─────────────────────────────────────────
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

        # ── Per-vehicle table ─────────────────────────────────────
        self._sec(sf, "POJAZDY – SZCZEGOLY")
        self._build_vehicle_table(sf)

        # ── Map legend ────────────────────────────────────────────
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

        # ── Event log ─────────────────────────────────────────────
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
            wrap,
            columns=cols,
            show="headings",
            height=min(n, 10),
            style="V.Treeview",
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

    # ══════════════════════════════════════════ HELPERS ═══════════

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
        self.canvas.delete("static")
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

    # ══════════════════════════════════════════ MAP DRAWING ════════

    def _draw_static_map(self):
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
                x1,
                y1,
                x2,
                y2,
                fill=color,
                width=w,
                dash=dash,
                tags="static",
            )

        hub_city = "Frankfurt" if self.cfg.scenario_logistics_center else None
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
                x,
                y - r - 6,
                text=name,
                fill=fill,
                font=("Arial", 7),
                tags="static",
            )

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
                    *pts,
                    fill=color,
                    width=1.5,
                    dash=(5, 3),
                    tags="route",
                )

    def _draw_vehicles(self):
        self.canvas.delete("vehicle")
        for v in self.engine.vehicles:
            lat, lon = self.engine.get_vehicle_position(v)
            x, y = self._xy(lat, lon)
            col = _STATUS_COLOR.get(v.status, C_IDLE)

            # Halo ring
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
            # Body
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
            # ID label
            self.canvas.create_text(
                x,
                y,
                text=str(v.id),
                fill=BG_DARK,
                font=("Arial", 7, "bold"),
                tags="vehicle",
            )

    # ══════════════════════════════════════════ SIMULATION LOOP ════

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
        self._draw_routes()
        self._draw_vehicles()
        self._update_stats()
        self._drain_log()

        if self.engine.time < self.cfg.simulation_duration:
            self.root.after(30, self._run)
        else:
            self.is_running = False
            self.btn_toggle.config(text="  KONIEC", bg=C_IDLE, state=tk.DISABLED)

    # ══════════════════════════════════════════ STATS UPDATE ═══════

    def _update_stats(self):
        stats = self.engine.get_stats()

        # Simulation overview
        pct = stats["time"] / self.cfg.simulation_duration * 100
        self._sim["progress"].config(
            text=f"{stats['time']:.1f} / {self.cfg.simulation_duration:.0f} h  ({pct:.0f}%)"
        )
        scen = []
        if self.cfg.scenario_breakdowns:
            scen.append("Awarie")
        if self.cfg.scenario_logistics_center:
            scen.append("Centrum log.")
        if self.cfg.scenario_random_events:
            scen.append("Utrudnienia drogowe")
        self._sim["scenario"].config(text=", ".join(scen) or "Bazowy (Scenariusz 1)")

        # Orders
        in_tr = sum(
            1
            for o in self.engine.orders
            if o.status
            in (OrderStatus.ASSIGNED, OrderStatus.IN_TRANSIT, OrderStatus.AT_HUB)
        )
        self._ord["total"].config(text=str(stats["total_orders"]))
        self._ord["pending"].config(text=str(stats["pending"]))
        self._ord["in_transit"].config(text=str(in_tr))
        self._ord["delivered"].config(text=str(stats["delivered"]))
        self._ord["on_time"].config(text=str(stats["on_time"]))
        late_txt = str(stats["late"])
        if stats["late"]:
            late_txt += f"  ({stats['total_delay_h']:.0f}h opoznienia)"
        self._ord["late"].config(text=late_txt)

        # Costs
        self._cost["fuel"].config(text=f"EUR {stats['total_fuel']:,.0f}")
        self._cost["penalty"].config(text=f"EUR {stats['total_penalty']:,.0f}")
        self._cost["repair"].config(text=f"EUR {stats['total_repair']:,.0f}")
        self._cost["total"].config(text=f"EUR {stats['total_cost']:,.0f}")

        # Fleet
        self._fleet["moving"].config(text=str(stats["vehicles_moving"]))
        self._fleet["idle"].config(text=str(stats["vehicles_idle"]))
        self._fleet["resting"].config(text=str(stats["vehicles_resting"]))
        self._fleet["broken"].config(text=str(stats["vehicles_broken"]))

        # Per-vehicle table
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
        if "delivered" in m:
            return "delivery"
        if "order" in m:
            return "order"
        if "resting" in m or "rested" in m:
            return "rest"
        if "stuck" in m or "broken" in m or "repair" in m:
            return "error"
        return ""
