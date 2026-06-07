"""
Experiment runner for the MISK simulation.

Each study sweeps one parameter over a grid for selected scenarios, repeats
every configuration over N seeds and averages the results. Writes runs.csv,
aggregated.csv, profit_history.json and meta.json.

Examples:
    python experiments.py
    python experiments.py --seeds 10
    python experiments.py --quick
    python experiments.py --only flota popyt
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import time
from pathlib import Path

from config import SimConfig
from headless import run_simulation

SCENARIOS: dict[str, dict] = {
    "normalny": {},
    "centrum": {"scenario_logistics_center": True},
    "utrudnienia": {"scenario_random_events": True},
    "awarie": {"scenario_breakdowns": True},
}

ALL_SCENARIOS = list(SCENARIOS)

# metric order = column order in the CSV files
METRICS = [
    "net_profit",
    "total_revenue",
    "total_cost",
    "total_fuel",
    "total_penalty",
    "total_repair",
    "total_orders",
    "delivered",
    "fulfillment_rate",
    "on_time",
    "late",
    "on_time_rate",
    "total_delay_h",
    "avg_delay_late_h",
    "total_distance_km",
    "breakdown_events",
    "road_events_total",
    "hub_via_delivered",
]


def metrics_from_result(r: dict) -> dict[str, float]:
    """Flatten one simulation result into a flat dict of metrics."""
    s = r["summary"]
    vehicles = r["vehicles"]
    total_orders = s["total_orders"]
    delivered = s["delivered"]
    late = s["late"]
    dist = sum(v["total_distance_km"] for v in vehicles)
    return {
        "net_profit": s["net_profit"],
        "total_revenue": s["total_revenue"],
        "total_cost": s["total_cost"],
        "total_fuel": s["total_fuel"],
        "total_penalty": s["total_penalty"],
        "total_repair": s["total_repair"],
        "total_orders": total_orders,
        "delivered": delivered,
        "fulfillment_rate": delivered / total_orders if total_orders else 0.0,
        "on_time": s["on_time"],
        "late": late,
        "on_time_rate": s["on_time"] / delivered if delivered else 0.0,
        "total_delay_h": s["total_delay_h"],
        "avg_delay_late_h": s["total_delay_h"] / late if late else 0.0,
        "total_distance_km": dist,
        "breakdown_events": s["breakdown_events"],
        "road_events_total": s["road_events_total"],
        "hub_via_delivered": s["hub_via_delivered"],
    }


@dataclasses.dataclass
class Study:
    name: str  # study name (column + file name)
    param: str  # swept SimConfig field ("scenario" for comparison)
    values: list  # grid of parameter values
    scenarios: list[str]  # scenarios to evaluate


def build_studies(quick: bool) -> list[Study]:
    if quick:
        return [
            Study("porownanie", "scenario", [None], ALL_SCENARIOS),
            Study("flota", "num_vehicles", [4, 8, 12], ALL_SCENARIOS),
            Study("popyt", "order_interval_mean", [2.0, 4.0], ALL_SCENARIOS),
            Study("zaloga", "double_crew", [False, True], ALL_SCENARIOS),
            Study("awarie_k", "breakdown_k", [1, 4], ["awarie"]),
            Study("hub_rate", "hub_via_rate", [0.1, 0.5], ["centrum"]),
            Study("zdarzenia", "event_interval_mean", [6.0, 24.0], ["utrudnienia"]),
        ]
    return [
        # compare the 4 scenarios at base parameters
        Study("porownanie", "scenario", [None], ALL_SCENARIOS),
        # fleet size
        Study("flota", "num_vehicles", [4, 6, 8, 10, 12, 16], ALL_SCENARIOS),
        # demand intensity (smaller interval = more orders)
        Study("popyt", "order_interval_mean", [1.5, 2.0, 3.0, 4.0, 6.0], ALL_SCENARIOS),
        # single vs double crew
        Study("zaloga", "double_crew", [False, True], ALL_SCENARIOS),
        # scenario-specific parameters
        Study("awarie_k", "breakdown_k", [1, 2, 4, 6], ["awarie"]),
        Study("hub_rate", "hub_via_rate", [0.1, 0.3, 0.5, 0.7], ["centrum"]),
        Study(
            "zdarzenia", "event_interval_mean", [6.0, 12.0, 24.0, 48.0], ["utrudnienia"]
        ),
    ]


def make_config(base: SimConfig, scenario: str, param: str, value) -> SimConfig:
    """Apply scenario flags and the swept parameter to the base config."""
    overrides = dict(SCENARIOS[scenario])
    if param != "scenario":
        overrides[param] = value
    return dataclasses.replace(base, **overrides)


def run_study(
    study: Study,
    base: SimConfig,
    seeds: list[int],
    run_rows: list[dict],
    profit_history: dict,
    verbose: bool,
) -> None:
    for value in study.values:
        for scenario in study.scenarios:
            per_run: list[dict] = []
            for seed in seeds:
                cfg = make_config(base, scenario, study.param, value)
                cfg = dataclasses.replace(cfg, seed=seed)
                result = run_simulation(cfg)
                m = metrics_from_result(result)
                per_run.append(m)

                row = {
                    "study": study.name,
                    "param": study.param,
                    "value": "" if value is None else value,
                    "scenario": scenario,
                    "seed": seed,
                    **m,
                }
                run_rows.append(row)

                # collect the time series only for the comparison study
                if study.name == "porownanie":
                    profit_history.setdefault(scenario, []).append(
                        result["profit_history"]
                    )

            if verbose:
                import statistics

                prof = statistics.mean(r["net_profit"] for r in per_run)
                ful = statistics.mean(r["fulfillment_rate"] for r in per_run)
                vlabel = "" if value is None else f"={value}"
                print(
                    f"  [{study.name}] {scenario:12s} {study.param}{vlabel:>8s}  "
                    f"profit={prof:>10,.0f}  realizacja={ful:.0%}",
                    flush=True,
                )


def aggregate(run_rows: list[dict]) -> list[dict]:
    """Group runs by (study, scenario, value) and compute mean/std/sem."""
    import numpy as np

    groups: dict[tuple, list[dict]] = {}
    for row in run_rows:
        key = (row["study"], row["param"], row["value"], row["scenario"])
        groups.setdefault(key, []).append(row)

    agg_rows: list[dict] = []
    dropped_total = 0
    for (study, param, value, scenario), rows in groups.items():
        n = len(rows)
        out = {
            "study": study,
            "param": param,
            "value": value,
            "scenario": scenario,
            "n": n,
        }
        for metric in METRICS:
            vals = np.array([float(r[metric]) for r in rows], dtype=float)
            finite = vals[np.isfinite(vals)]
            n_drop = len(vals) - len(finite)
            dropped_total += n_drop
            nf = len(finite)
            mean = float(finite.mean()) if nf else float("nan")
            std = float(finite.std(ddof=1)) if nf > 1 else 0.0
            sem = std / (nf**0.5) if nf > 1 else 0.0
            out[f"{metric}_mean"] = round(mean, 4)
            out[f"{metric}_std"] = round(std, 4)
            out[f"{metric}_sem"] = round(sem, 4)
        agg_rows.append(out)
    if dropped_total:
        print(
            f"  [uwaga] pominieto {dropped_total} nieskonczonych wartosci "
            f"metryk przy usrednianiu"
        )
    return agg_rows


def average_profit_history(profit_history: dict) -> dict:
    """Average the revenue/cost series across seeds, hour by hour."""
    import numpy as np

    out: dict = {}
    for scenario, runs in profit_history.items():
        if not runs:
            continue
        n_hours = min(len(h) for h in runs)
        times = [runs[0][i]["time"] for i in range(n_hours)]
        rev = np.array([[h[i]["revenue"] for i in range(n_hours)] for h in runs])
        cost = np.array([[h[i]["cost"] for i in range(n_hours)] for h in runs])
        out[scenario] = {
            "time": times,
            "revenue_mean": rev.mean(axis=0).round(2).tolist(),
            "cost_mean": cost.mean(axis=0).round(2).tolist(),
            "profit_mean": (rev - cost).mean(axis=0).round(2).tolist(),
        }
    return out


def write_runs_csv(path: Path, run_rows: list[dict]) -> None:
    fields = ["study", "param", "value", "scenario", "seed", *METRICS]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in run_rows:
            w.writerow({k: row[k] for k in fields})


def write_aggregated_csv(path: Path, agg_rows: list[dict]) -> None:
    fields = ["study", "param", "value", "scenario", "n"]
    for metric in METRICS:
        fields += [f"{metric}_mean", f"{metric}_std", f"{metric}_sem"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in agg_rows:
            w.writerow(row)


def main(argv=None):
    p = argparse.ArgumentParser(description="Run MISK simulation experiment suite.")
    p.add_argument(
        "--seeds", type=int, default=20, help="Seeds per config (default 20)"
    )
    p.add_argument("--seed0", type=int, default=1000, help="First seed (default 1000)")
    p.add_argument("--out", type=str, default="results", help="Output directory")
    p.add_argument("--vehicles", type=int, default=8, help="Base num_vehicles")
    p.add_argument("--duration", type=float, default=168.0, help="Sim duration (h)")
    p.add_argument("--quick", action="store_true", help="Tiny smoke test")
    p.add_argument(
        "--only",
        nargs="+",
        default=None,
        help="Run only these studies by name (e.g. flota popyt)",
    )
    p.add_argument(
        "--reaggregate",
        action="store_true",
        help="Skip simulation; rebuild aggregated.csv from existing runs.csv",
    )
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.reaggregate:
        out = Path(args.out)
        with open(out / "runs.csv", encoding="utf-8") as f:
            run_rows = [
                {**row, **{m: float(row[m]) for m in METRICS}}
                for row in csv.DictReader(f)
            ]
        write_aggregated_csv(out / "aggregated.csv", aggregate(run_rows))
        print(f"Przeliczono → {out / 'aggregated.csv'} ({len(run_rows)} przebiegów)")
        return

    if args.quick:
        args.seeds = min(args.seeds, 3)

    seeds = list(range(args.seed0, args.seed0 + args.seeds))
    base = SimConfig(
        num_vehicles=args.vehicles,
        simulation_duration=args.duration,
    )
    studies = build_studies(args.quick)
    if args.only:
        studies = [s for s in studies if s.name in set(args.only)]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    n_runs = sum(len(s.values) * len(s.scenarios) for s in studies) * len(seeds)
    verbose = not args.quiet
    if verbose:
        print(
            f"Studia: {[s.name for s in studies]}\n"
            f"Ziarna: {len(seeds)} ({seeds[0]}..{seeds[-1]})  "
            f"Pojazdy bazowo: {args.vehicles}  Czas: {args.duration}h\n"
            f"Łącznie przebiegów: {n_runs}\n"
        )

    run_rows: list[dict] = []
    profit_history: dict = {}
    t0 = time.time()
    for study in studies:
        if verbose:
            print(f"== Studium: {study.name} ==", flush=True)
        run_study(study, base, seeds, run_rows, profit_history, verbose)
    elapsed = time.time() - t0

    agg_rows = aggregate(run_rows)
    hist = average_profit_history(profit_history)

    write_runs_csv(out / "runs.csv", run_rows)
    write_aggregated_csv(out / "aggregated.csv", agg_rows)
    with open(out / "profit_history.json", "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2, ensure_ascii=False)
    with open(out / "meta.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "seeds": seeds,
                "base_vehicles": args.vehicles,
                "duration_h": args.duration,
                "studies": [
                    {
                        "name": s.name,
                        "param": s.param,
                        "values": s.values,
                        "scenarios": s.scenarios,
                    }
                    for s in studies
                ],
                "n_runs": len(run_rows),
                "elapsed_s": round(elapsed, 1),
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    if verbose:
        print(
            f"\nGotowe: {len(run_rows)} przebiegów w {elapsed / 60:.1f} min\n"
            f"  → {out / 'runs.csv'}\n"
            f"  → {out / 'aggregated.csv'}\n"
            f"  → {out / 'profit_history.json'}\n"
            f"  → {out / 'meta.json'}"
        )


if __name__ == "__main__":
    main()
