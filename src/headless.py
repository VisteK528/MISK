"""
Run the simulation without the GUI (for batch runs).

Functions: run_simulation, run_batch, seed_sweep, scenario_matrix.

CLI examples:
    python headless.py                          # 1 run, seed 42
    python headless.py --runs 10                # seeds 42-51
    python headless.py --seeds 1,2,3 --sc 2,3   # scenarios 2 and 3
    python headless.py --matrix                 # all flag combinations
    python headless.py --runs 5 --out results/  # save JSON to a directory
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from itertools import product
from pathlib import Path

from config import SimConfig
from engine import SimulationEngine


def run_simulation(config: SimConfig) -> dict:
    """Run one simulation to the end and return its result dict."""
    engine = SimulationEngine(config)
    engine.run_to_end()
    return engine.export_data()


def run_batch(
    configs: list[SimConfig],
    *,
    verbose: bool = True,
    out_dir: str | Path | None = None,
) -> list[dict]:
    """
    Run each config in turn and return the list of results.
    If out_dir is given, each result is also saved to a JSON file.
    """
    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    total = len(configs)
    for i, cfg in enumerate(configs):
        label = _config_label(cfg)
        if verbose:
            print(f"[{i + 1}/{total}] {label} ...", end=" ", flush=True)

        result = run_simulation(cfg)
        result["run_index"] = i
        results.append(result)

        if verbose:
            stats = result["summary"]
            profit = stats["net_profit"]
            print(
                f"done  profit=€{profit:,.0f}  "
                f"delivered={stats['delivered']}/{stats['total_orders']}"
            )

        if out_dir is not None:
            fname = f"run_{i:03d}_{label}.json"
            fpath = out_path / fname
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

    return results


def seed_sweep(base: SimConfig, seeds) -> list[SimConfig]:
    """One config per seed, all other settings unchanged."""
    return [dataclasses.replace(base, seed=int(s)) for s in seeds]


def scenario_matrix(base: SimConfig) -> list[SimConfig]:
    """All 8 combinations of the three scenario flags at the same seed."""
    configs = []
    for sc2, sc3, sc4 in product([False, True], repeat=3):
        configs.append(
            dataclasses.replace(
                base,
                scenario_breakdowns=sc2,
                scenario_logistics_center=sc3,
                scenario_random_events=sc4,
            )
        )
    return configs


def _config_label(cfg: SimConfig) -> str:
    flags = (
        "".join(
            abbr
            for flag, abbr in [
                (cfg.scenario_breakdowns, "sc2"),
                (cfg.scenario_logistics_center, "sc3"),
                (cfg.scenario_random_events, "sc4"),
            ]
            if flag
        )
        or "base"
    )
    return f"seed{cfg.seed}_{flags}"


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Run MISK transport simulation in headless mode.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python headless.py --runs 10 --out results/\n"
            "  python headless.py --seeds 1,2,3 --sc 2,3\n"
            "  python headless.py --matrix --seed 0"
        ),
    )
    p.add_argument(
        "--runs",
        type=int,
        default=None,
        metavar="N",
        help="Number of runs using consecutive seeds starting from --seed",
    )
    p.add_argument(
        "--seeds",
        type=str,
        default=None,
        metavar="S1,S2,...",
        help="Comma-separated explicit seed list (overrides --runs)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        metavar="N",
        help="Base seed (default 42); start of range for --runs",
    )
    p.add_argument(
        "--sc",
        type=str,
        default="",
        metavar="2,3,4",
        help="Comma-separated scenario numbers to enable (e.g. '2,3')",
    )
    p.add_argument(
        "--matrix",
        action="store_true",
        help="Run all 8 scenario on/off combinations (ignores --sc)",
    )
    p.add_argument(
        "--vehicles",
        type=int,
        default=8,
        metavar="N",
        help="Number of vehicles (default 8)",
    )
    p.add_argument(
        "--duration",
        type=float,
        default=168.0,
        metavar="H",
        help="Simulation duration in hours (default 168)",
    )
    p.add_argument(
        "--out",
        type=str,
        default=None,
        metavar="DIR",
        help="Directory to save per-run JSON files",
    )
    p.add_argument(
        "--summary",
        type=str,
        default=None,
        metavar="FILE",
        help="Path to save a combined summary JSON (all runs)",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-run progress output",
    )
    return p.parse_args(argv)


def _build_base(args) -> SimConfig:
    sc = set(args.sc.split(",")) if args.sc.strip() else set()
    return SimConfig(
        num_vehicles=args.vehicles,
        simulation_duration=args.duration,
        seed=args.seed,
        scenario_breakdowns="2" in sc,
        scenario_logistics_center="3" in sc,
        scenario_random_events="4" in sc,
    )


def main(argv=None):
    args = _parse_args(argv)
    base = _build_base(args)

    if args.matrix:
        configs = scenario_matrix(base)
    elif args.seeds:
        seeds = [int(s.strip()) for s in args.seeds.split(",")]
        configs = seed_sweep(base, seeds)
    elif args.runs:
        configs = seed_sweep(base, range(args.seed, args.seed + args.runs))
    else:
        configs = [base]

    results = run_batch(
        configs,
        verbose=not args.quiet,
        out_dir=args.out,
    )

    if args.summary:
        summary_path = Path(args.summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        if not args.quiet:
            print(f"\nSummary saved → {summary_path}")

    if not args.quiet:
        print(f"\n{len(results)} run(s) complete.")

    return results


if __name__ == "__main__":
    main(sys.argv[1:])
