"""V5 Benchmark - Main Entry Point.

Runs the complete benchmark evaluation of the V5 football simulator
against real World Cup 2026 match data.

Usage:
    python -m fifa_data.benchmark.run_benchmark
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIFA_DATA = HERE.parent

from fifa_data.benchmark.data_loader import load_real_matches, load_groups, load_team_metrics
from fifa_data.benchmark.simulation_runner import simulate_all_matches
from fifa_data.benchmark.metrics import compute_match_metrics, compute_tournament_summary
from fifa_data.benchmark.calibration import compute_calibration_metrics
from fifa_data.benchmark.error_analysis import analyze_systematic_errors
from fifa_data.benchmark.visualizations import generate_all_graphs
from fifa_data.benchmark.report_generator import generate_match_reports, generate_tournament_report


def run_benchmark(output_dir: str | None = None, verbose: bool = True) -> dict:
    """Run the complete V5 benchmark evaluation.

    Args:
        output_dir: Directory for output files. Defaults to benchmark/output/
        verbose: Print progress updates.

    Returns:
        Dictionary with all benchmark results.
    """
    out = Path(output_dir) if output_dir else HERE / "output"
    out.mkdir(parents=True, exist_ok=True)

    if verbose:
        print("=" * 70)
        print("  V5 FOOTBALL SIMULATOR - OFFICIAL BENCHMARK")
        print("=" * 70)
        print()

    # ── Step 1: Load real match data ──────────────────────────────────────
    if verbose:
        print("[1/8] Loading real match data...")
    t0 = time.time()
    real_matches = load_real_matches()
    groups = load_groups()
    team_metrics = load_team_metrics()
    if verbose:
        print(f"  Loaded {len(real_matches)} real matches in {time.time()-t0:.1f}s")
        stages = {}
        for m in real_matches:
            s = m.get("stage", "Unknown")
            stages[s] = stages.get(s, 0) + 1
        for s, c in sorted(stages.items()):
            print(f"    {s}: {c} matches")
        print()

    # ── Step 2: Run V5 simulations ────────────────────────────────────────
    if verbose:
        print("[2/8] Running V5 simulations for all matches...")
    t0 = time.time()
    sim_results = simulate_all_matches(real_matches, groups, team_metrics, verbose=verbose)
    if verbose:
        print(f"  Simulated {len(sim_results)} matches in {time.time()-t0:.1f}s")
        print()

    # ── Step 3: Compute match-level metrics ───────────────────────────────
    if verbose:
        print("[3/8] Computing match-level metrics...")
    t0 = time.time()
    match_metrics = compute_match_metrics(sim_results, real_matches)
    if verbose:
        print(f"  Computed metrics for {len(match_metrics)} matches in {time.time()-t0:.1f}s")
        print()

    # ── Step 4: Compute tournament summary ────────────────────────────────
    if verbose:
        print("[4/8] Computing tournament summary...")
    t0 = time.time()
    tournament_summary = compute_tournament_summary(match_metrics)
    if verbose:
        print(f"  Summary computed in {time.time()-t0:.1f}s")
        print()

    # ── Step 5: Compute calibration metrics ───────────────────────────────
    if verbose:
        print("[5/8] Computing calibration metrics...")
    t0 = time.time()
    calibration = compute_calibration_metrics(match_metrics)
    if verbose:
        print(f"  Calibration computed in {time.time()-t0:.1f}s")
        print()

    # ── Step 6: Error analysis ────────────────────────────────────────────
    if verbose:
        print("[6/8] Running error analysis...")
    t0 = time.time()
    error_analysis = analyze_systematic_errors(match_metrics, real_matches)
    if verbose:
        print(f"  Error analysis completed in {time.time()-t0:.1f}s")
        print()

    # ── Step 7: Generate visualizations ───────────────────────────────────
    if verbose:
        print("[7/8] Generating visualizations...")
    t0 = time.time()
    graphs = generate_all_graphs(match_metrics, calibration, tournament_summary, out)
    if verbose:
        print(f"  Generated {len(graphs)} graphs in {time.time()-t0:.1f}s")
        print()

    # ── Step 8: Generate reports ──────────────────────────────────────────
    if verbose:
        print("[8/8] Generating reports...")
    t0 = time.time()
    generate_match_reports(match_metrics, sim_results, real_matches, out)
    generate_tournament_report(
        tournament_summary, calibration, error_analysis,
        match_metrics, sim_results, real_matches, out
    )
    if verbose:
        print(f"  Reports generated in {time.time()-t0:.1f}s")
        print()

    # ── Save JSON summary ─────────────────────────────────────────────────
    summary_json = {
        "version": "V5",
        "total_matches": len(match_metrics),
        "tournament_summary": tournament_summary,
        "calibration": calibration,
        "error_analysis": error_analysis,
    }
    json_path = out / "benchmark_summary.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary_json, f, indent=2, default=str)

    # ── Save CSV ──────────────────────────────────────────────────────────
    csv_path = out / "benchmark_matches.csv"
    _save_csv(match_metrics, csv_path)

    if verbose:
        print("=" * 70)
        print("  BENCHMARK COMPLETE")
        print("=" * 70)
        print(f"  Output directory: {out}")
        print(f"  Files generated:")
        print(f"    - benchmark_summary.json")
        print(f"    - benchmark_matches.csv")
        print(f"    - tournament_report.md")
        print(f"    - match_reports/ ({len(match_metrics)} match reports)")
        print(f"    - graphs/ ({len(graphs)} PNG files)")
        print()

    return {
        "match_metrics": match_metrics,
        "tournament_summary": tournament_summary,
        "calibration": calibration,
        "error_analysis": error_analysis,
        "graphs": graphs,
        "output_dir": str(out),
    }


def _save_csv(match_metrics: list[dict], path: Path) -> None:
    """Save match metrics to CSV."""
    import csv
    if not match_metrics:
        return
    fieldnames = list(match_metrics[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in match_metrics:
            writer.writerow({k: str(v) for k, v in row.items()})


if __name__ == "__main__":
    run_benchmark()
