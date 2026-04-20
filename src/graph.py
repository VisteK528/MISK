import networkx as nx

# City data - latitude and longitude
CITIES = {
    "Lisbon": (38.72, -9.14),
    "Madrid": (40.42, -3.70),
    "Barcelona": (41.39, 2.17),
    "Paris": (48.86, 2.35),
    "Lyon": (45.76, 4.83),
    "Brussels": (50.85, 4.35),
    "Amsterdam": (52.37, 4.90),
    "London": (51.51, -0.13),
    "Frankfurt": (50.11, 8.68),
    "Hamburg": (53.55, 9.99),
    "Berlin": (52.52, 13.41),
    "Copenhagen": (55.68, 12.57),
    "Stockholm": (59.33, 18.07),
    "Munich": (48.14, 11.58),
    "Zurich": (47.38, 8.54),
    "Milan": (45.46, 9.19),
    "Rome": (41.90, 12.50),
    "Vienna": (48.21, 16.37),
    "Prague": (50.08, 14.44),
    "Warsaw": (52.23, 21.01),
    "Budapest": (47.50, 19.04),
    "Bucharest": (44.43, 26.10),
    "Sofia": (42.70, 23.32),
    "Athens": (37.98, 23.73),
}

# Distance in km
ROADS = [
    ("Lisbon", "Madrid", 625),
    ("Madrid", "Barcelona", 620),
    ("Madrid", "Paris", 1275),
    ("Barcelona", "Lyon", 645),
    ("Barcelona", "Milan", 1015),
    ("Paris", "Lyon", 465),
    ("Paris", "Brussels", 310),
    ("Paris", "London", 460),
    ("Brussels", "Amsterdam", 210),
    ("Brussels", "Frankfurt", 395),
    ("Amsterdam", "Hamburg", 465),
    ("Amsterdam", "Frankfurt", 440),
    ("Frankfurt", "Berlin", 545),
    ("Frankfurt", "Munich", 390),
    ("Frankfurt", "Zurich", 400),
    ("Hamburg", "Berlin", 290),
    ("Hamburg", "Copenhagen", 465),
    ("Berlin", "Prague", 350),
    ("Berlin", "Warsaw", 575),
    ("Berlin", "Copenhagen", 445),
    ("Copenhagen", "Stockholm", 660),
    ("Munich", "Zurich", 315),
    ("Munich", "Vienna", 435),
    ("Munich", "Milan", 590),
    ("Zurich", "Milan", 295),
    ("Milan", "Rome", 575),
    ("Vienna", "Prague", 330),
    ("Vienna", "Budapest", 245),
    ("Budapest", "Warsaw", 885),
    ("Budapest", "Bucharest", 830),
    ("Budapest", "Sofia", 790),
    ("Bucharest", "Sofia", 395),
    ("Sofia", "Athens", 800),
    ("Rome", "Athens", 1500),
    ("Lyon", "Zurich", 545),
    ("Lyon", "Milan", 505),
    ("Warsaw", "Prague", 680),
]

START_CITIES = [
    "Frankfurt",
    "Paris",
    "Milan",
    "Warsaw",
    "Madrid",
    "London",
    "Vienna",
    "Amsterdam",
    "Berlin",
    "Munich",
    "Prague",
    "Budapest",
    "Rome",
    "Barcelona",
    "Hamburg",
    "Brussels",
    "Lyon",
    "Zurich",
    "Copenhagen",
    "Stockholm",
    "Bucharest",
    "Sofia",
    "Athens",
    "Lisbon",
]


class CityGraph:
    def __init__(self):
        self.G = nx.Graph()

        for name, (lat, lon) in CITIES.items():
            self.G.add_node(name, lat=lat, lon=lon)

        for c1, c2, dist in ROADS:
            self.G.add_edge(c1, c2, distance_km=dist, speed_multiplier=1.0)

    @property
    def cities(self) -> dict[str, tuple[float, float]]:
        """Return dict  {city_name: (lat, lon)}  from NetworkX node attrs."""
        return {n: (d["lat"], d["lon"]) for n, d in self.G.nodes(data=True)}

    def get_distance(self, c1: str, c2: str) -> float | None:
        if self.G.has_edge(c1, c2):
            return self.G[c1][c2]["distance_km"]
        return None

    def get_multiplier(self, c1: str, c2: str) -> float:
        if self.G.has_edge(c1, c2):
            return self.G[c1][c2]["speed_multiplier"]
        return 1.0

    def set_multiplier(self, c1: str, c2: str, mult: float):
        if self.G.has_edge(c1, c2):
            self.G[c1][c2]["speed_multiplier"] = mult

    def get_all_road_keys(self) -> set[tuple[str, str]]:
        """Return set of sorted (city_a, city_b) tuples for every edge."""
        return {tuple(sorted(e)) for e in self.G.edges()}

    def dijkstra(self, start: str, end: str, speed: float):
        try:
            path = nx.dijkstra_path(
                self.G,
                start,
                end,
                weight=lambda u, v, d: (
                    d["distance_km"] / (speed / d["speed_multiplier"])
                    if d["speed_multiplier"] < 100
                    else float("inf")
                ),
            )
            total_hours = nx.dijkstra_path_length(
                self.G,
                start,
                end,
                weight=lambda u, v, d: (
                    d["distance_km"] / (speed / d["speed_multiplier"])
                    if d["speed_multiplier"] < 100
                    else float("inf")
                ),
            )
            return path, total_hours
        except nx.NetworkXNoPath:
            return [], float("inf")
