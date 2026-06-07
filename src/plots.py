"""
Generate summary charts from experiment output (see experiments.py).

Reads ``aggregated.csv`` + ``profit_history.json`` from a results directory and
writes PNG charts (Polish labels) into ``<results>/plots/``.

Usage
-----
    python plots.py                    # read results/, write results/plots/
    python plots.py --dir results_quick
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

DISPLAY = {
    "normalny": "Normalny",
    "centrum": "Centrum logist.",
    "utrudnienia": "Utrudnienia drog.",
    "awarie": "Awarie pojazdów",
}
COLORS = {
    "normalny": "#2c7fb8",
    "centrum": "#41ab5d",
    "utrudnienia": "#fe9929",
    "awarie": "#e34a33",
}
SCENARIO_ORDER = ["normalny", "centrum", "utrudnienia", "awarie"]

PARAM_LABEL = {
    "num_vehicles": "Liczba pojazdów",
    "order_interval_mean": "Śr. odstęp między zleceniami [h]\n(mniej = większy popyt)",
    "breakdown_k": "Liczba awarii (breakdown_k)",
    "hub_via_rate": "Udział zleceń przez hub",
    "event_interval_mean": "Śr. odstęp między zdarzeniami [h]\n(mniej = częstsze)",
}

_eur = FuncFormatter(lambda x, _: f"{x / 1000:.0f}k")
_pct = FuncFormatter(lambda x, _: f"{x * 100:.0f}%")


def load_aggregated(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            parsed = {
                "study": row["study"],
                "param": row["param"],
                "scenario": row["scenario"],
                "value_raw": row["value"],
                "n": int(row["n"]),
            }
            # numeric value (comparison study has empty value)
            try:
                parsed["value"] = float(row["value"])
            except ValueError:
                parsed["value"] = row["value"]
            for k, v in row.items():
                if k.endswith(("_mean", "_std", "_sem")):
                    parsed[k] = float(v)
            rows.append(parsed)
    return rows


def study_rows(rows, study, scenario=None):
    out = [r for r in rows if r["study"] == study]
    if scenario is not None:
        out = [r for r in out if r["scenario"] == scenario]
    return out


def sweep_lines(ax, rows, study, metric, fmt=None):
    """Plot <metric>_mean vs numeric value, one line per scenario, with sem bars."""
    for sc in SCENARIO_ORDER:
        srows = [r for r in study_rows(rows, study, sc)]
        if not srows:
            continue
        srows.sort(key=lambda r: r["value"])
        xs = [r["value"] for r in srows]
        ys = [r[f"{metric}_mean"] for r in srows]
        es = [r[f"{metric}_sem"] for r in srows]
        ax.errorbar(
            xs,
            ys,
            yerr=es,
            marker="o",
            capsize=3,
            color=COLORS[sc],
            label=DISPLAY[sc],
        )
    if fmt:
        ax.yaxis.set_major_formatter(fmt)
    ax.grid(True, alpha=0.3)


def save(fig, out_dir: Path, name: str):
    fig.tight_layout()
    path = out_dir / name
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"  → {path}")


def plot_comparison(rows, out: Path):
    comp = {r["scenario"]: r for r in study_rows(rows, "porownanie")}
    scs = [s for s in SCENARIO_ORDER if s in comp]
    if not scs:
        return
    labels = [DISPLAY[s] for s in scs]
    colors = [COLORS[s] for s in scs]

    # 1) Net profit
    fig, ax = plt.subplots(figsize=(7, 4.5))
    vals = [comp[s]["net_profit_mean"] for s in scs]
    errs = [comp[s]["net_profit_sem"] for s in scs]
    ax.bar(labels, vals, yerr=errs, capsize=4, color=colors)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Zysk netto [EUR]")
    ax.yaxis.set_major_formatter(_eur)
    ax.set_title("Zysk netto wg scenariusza (średnia ± SEM)")
    ax.grid(True, axis="y", alpha=0.3)
    save(fig, out, "porownanie_zysk.png")

    # 2) Fulfillment & on-time rate
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, metric, title in [
        (axes[0], "fulfillment_rate", "Wskaźnik realizacji zleceń"),
        (axes[1], "on_time_rate", "Udział dostaw na czas"),
    ]:
        vals = [comp[s][f"{metric}_mean"] for s in scs]
        errs = [comp[s][f"{metric}_sem"] for s in scs]
        ax.bar(labels, vals, yerr=errs, capsize=4, color=colors)
        ax.set_ylim(0, 1)
        ax.yaxis.set_major_formatter(_pct)
        ax.set_title(title)
        ax.grid(True, axis="y", alpha=0.3)
        ax.tick_params(axis="x", labelrotation=15)
    save(fig, out, "porownanie_realizacja.png")

    # 3) Cost composition (stacked) + revenue marker
    fig, ax = plt.subplots(figsize=(8, 4.8))
    fuel = [comp[s]["total_fuel_mean"] for s in scs]
    pen = [comp[s]["total_penalty_mean"] for s in scs]
    rep = [comp[s]["total_repair_mean"] for s in scs]
    rev = [comp[s]["total_revenue_mean"] for s in scs]
    ax.bar(labels, fuel, label="Paliwo", color="#7fcdbb")
    ax.bar(labels, pen, bottom=fuel, label="Kary za opóźnienia", color="#fdae61")
    bottom2 = [f + p for f, p in zip(fuel, pen)]
    ax.bar(labels, rep, bottom=bottom2, label="Naprawy", color="#d7191c")
    ax.plot(labels, rev, "k_", markersize=28, markeredgewidth=3, label="Przychód")
    ax.set_ylabel("EUR")
    ax.yaxis.set_major_formatter(_eur)
    ax.set_title("Struktura kosztów vs przychód (średnia)")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    ax.tick_params(axis="x", labelrotation=15)
    save(fig, out, "porownanie_koszty.png")


def plot_sweep(rows, out: Path, study: str, param: str, fname: str):
    if not study_rows(rows, study):
        return
    xlabel = PARAM_LABEL.get(param, param)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    sweep_lines(axes[0], rows, study, "net_profit", _eur)
    axes[0].axhline(0, color="black", lw=0.8)
    axes[0].set_ylabel("Zysk netto [EUR]")
    axes[0].set_xlabel(xlabel)
    axes[0].set_title("Zysk netto")
    axes[0].legend(fontsize=8)

    sweep_lines(axes[1], rows, study, "fulfillment_rate", _pct)
    axes[1].set_ylim(0, 1)
    axes[1].set_ylabel("Wskaźnik realizacji")
    axes[1].set_xlabel(xlabel)
    axes[1].set_title("Realizacja zleceń")
    axes[1].legend(fontsize=8)
    fig.suptitle(f"Wpływ parametru: {param}", fontsize=13)
    save(fig, out, fname)


def plot_double_crew(rows, out: Path):
    srows = study_rows(rows, "zaloga")
    if not srows:
        return
    scs = [s for s in SCENARIO_ORDER if any(r["scenario"] == s for r in srows)]
    import numpy as np

    x = np.arange(len(scs))
    width = 0.38
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for i, crew in enumerate(["False", "True"]):
        vals, errs = [], []
        for sc in scs:
            match = [r for r in srows if r["scenario"] == sc and r["value_raw"] == crew]
            vals.append(match[0]["net_profit_mean"] if match else 0)
            errs.append(match[0]["net_profit_sem"] if match else 0)
        label = "Podwójna załoga" if crew == "True" else "Pojedyncza załoga"
        color = "#2b8cbe" if crew == "True" else "#a6bddb"
        ax.bar(
            x + (i - 0.5) * width,
            vals,
            width,
            yerr=errs,
            capsize=3,
            label=label,
            color=color,
        )
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([DISPLAY[s] for s in scs], rotation=15)
    ax.set_ylabel("Zysk netto [EUR]")
    ax.yaxis.set_major_formatter(_eur)
    ax.set_title("Wpływ podwójnej załogi (brak postojów) na zysk")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    save(fig, out, "zaloga_zysk.png")


def plot_history(hist_path: Path, out: Path):
    if not hist_path.exists():
        return
    with open(hist_path, encoding="utf-8") as f:
        hist = json.load(f)
    if not hist:
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    for sc in SCENARIO_ORDER:
        if sc not in hist:
            continue
        h = hist[sc]
        ax.plot(h["time"], h["profit_mean"], color=COLORS[sc], label=DISPLAY[sc])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("Czas symulacji [h]")
    ax.set_ylabel("Skumulowany zysk netto [EUR]")
    ax.yaxis.set_major_formatter(_eur)
    ax.set_title("Przebieg skumulowanego zysku w czasie (średnia z ziaren)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    save(fig, out, "historia_zysku.png")


def main(argv=None):
    p = argparse.ArgumentParser(description="Plot MISK experiment results.")
    p.add_argument("--dir", type=str, default="results", help="Results directory")
    args = p.parse_args(argv)

    base = Path(args.dir)
    rows = load_aggregated(base / "aggregated.csv")
    out = base / "plots"
    out.mkdir(parents=True, exist_ok=True)

    print(f"Generuję wykresy → {out}")
    plot_comparison(rows, out)
    plot_sweep(rows, out, "flota", "num_vehicles", "flota.png")
    plot_sweep(rows, out, "popyt", "order_interval_mean", "popyt.png")
    plot_double_crew(rows, out)
    plot_sweep(rows, out, "awarie_k", "breakdown_k", "awarie_k.png")
    plot_sweep(rows, out, "hub_rate", "hub_via_rate", "hub_rate.png")
    plot_sweep(rows, out, "zdarzenia", "event_interval_mean", "zdarzenia.png")
    plot_history(base / "profit_history.json", out)
    print("Gotowe.")


if __name__ == "__main__":
    main()
