from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = PROJECT_ROOT / "Kairos-Scheduler-main"

for path in (PROJECT_ROOT, KAIROS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from factory_sim import (
    build_schedule_bundle_from_kairos,
    build_product_tracker_lines,
    run_week,
    validate_kairos_solution,
    write_product_tracker,
)
from examples.kairos_stochastic_demo import (
    build_stochastic_execution_bundle,
    build_stochastic_execution_hooks,
)
from examples.kairos_validation_demo import (
    DEMO_ABSOLUTE_GAP_LIMIT,
    DEMO_ORTOOLS_LOGGING_ENABLED,
    DEMO_RELATIVE_GAP_LIMIT,
    DEMO_SOLVE_TIME_LIMIT_SECONDS,
    DEMO_SOLVER_LOGGING_ENABLED,
    DEMO_SOLVER_WORKERS,
    solve_large_demo_problem,
)


def main(
    *,
    mode: str = "stochastic",
    seed: int = 17,
    time_limit_seconds: int = DEMO_SOLVE_TIME_LIMIT_SECONDS,
    logging_enabled: bool = DEMO_SOLVER_LOGGING_ENABLED,
    ortools_logging: bool = DEMO_ORTOOLS_LOGGING_ENABLED,
    workers: int | None = DEMO_SOLVER_WORKERS,
    relative_gap_limit: float | None = DEMO_RELATIVE_GAP_LIMIT,
    absolute_gap_limit: float | None = DEMO_ABSOLUTE_GAP_LIMIT,
    preview_lines: int = 120,
    include_idle: bool = True,
) -> None:
    problem, solution = solve_large_demo_problem(
        time_limit_seconds=time_limit_seconds,
        logging_enabled=logging_enabled,
        ortools_logging=ortools_logging,
        workers=workers,
        relative_gap_limit=relative_gap_limit,
        absolute_gap_limit=absolute_gap_limit,
    )
    if not solution.is_success:
        raise RuntimeError(f"Kairos failed to produce a usable schedule: {solution.status}")

    output_dir = PROJECT_ROOT / "examples" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    if mode == "validation":
        report = validate_kairos_solution(problem, solution, trace=True)
        schedule_bundle = report.schedule_bundle
        simulation_result = report.simulation_result
        output_path = output_dir / "product_tracker_validation.txt"
        header_lines = [
            f"Product Tracker - Validation Replay",
            f"Problem: {problem.name}",
            f"Kairos status: {solution.status}",
            f"Exact replay match: {report.exact_match}",
            f"Planned makespan: {report.planned_makespan:.2f} min",
            f"Actual makespan: {report.actual_makespan:.2f} min" if report.actual_makespan is not None else "Actual makespan: N/A",
            f"Machines: {len(schedule_bundle.machines)} | Batches: {len(schedule_bundle.batches)} | Operations: {len(schedule_bundle.schedule_operations)}",
        ]
    else:
        conversion = build_schedule_bundle_from_kairos(problem, solution)
        schedule_bundle = build_stochastic_execution_bundle(conversion.schedule_bundle)
        simulation_result = run_week(
            schedule_bundle,
            seed=seed,
            hooks=build_stochastic_execution_hooks(),
            trace=True,
        )
        output_path = output_dir / "product_tracker_stochastic.txt"
        actual_end_times = [
            operation.actual_end for operation in simulation_result.operations if operation.actual_end is not None
        ]
        header_lines = [
            f"Product Tracker - Stochastic Execution",
            f"Problem: {problem.name}",
            f"Kairos status: {solution.status}",
            f"Seed: {seed}",
            f"Planned makespan: {max(operation.planned_end for operation in schedule_bundle.schedule_operations):.2f} min",
            (
                f"Actual completed makespan: {max(actual_end_times):.2f} min"
                if actual_end_times
                else "Actual completed makespan: N/A"
            ),
            f"Completed batches: {len([batch for batch in simulation_result.batch_summaries if batch.completed])}",
            f"Leftover batches: {len(simulation_result.leftover_batches)}",
            f"Machines: {len(schedule_bundle.machines)} | Batches: {len(schedule_bundle.batches)} | Operations: {len(schedule_bundle.schedule_operations)}",
        ]

    lines = write_product_tracker(
        output_path,
        schedule_bundle,
        simulation_result,
        include_idle=include_idle,
        header_lines=header_lines,
    )

    print(f"Tracker mode: {mode}")
    print(f"Tracker file: {output_path}")
    print(f"Total tracker lines: {len(lines)}")

    if preview_lines > 0:
        print("")
        print("Preview:")
        preview = lines[:preview_lines]
        for line in preview:
            print(line)
        if len(lines) > preview_lines:
            print("")
            print(f"... {len(lines) - preview_lines} more lines written to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a product tracker demo for the factory simulation.")
    parser.add_argument(
        "--mode",
        choices=("validation", "stochastic"),
        default="stochastic",
        help="Validation replays the Kairos schedule exactly. Stochastic runs the normal stochastic simulation.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=17,
        help="Random seed for stochastic simulation mode.",
    )
    parser.add_argument(
        "--time-limit",
        type=int,
        default=DEMO_SOLVE_TIME_LIMIT_SECONDS,
        help="Kairos CP-SAT time limit in seconds.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Override the CP-SAT worker count. By default Kairos uses the system CPU count.",
    )
    parser.add_argument(
        "--relative-gap",
        type=float,
        default=None,
        help="Stop early when the relative optimality gap drops below this value.",
    )
    parser.add_argument(
        "--absolute-gap",
        type=float,
        default=None,
        help="Stop early when the absolute objective gap drops below this value.",
    )
    parser.add_argument(
        "--quiet-kairos",
        action="store_true",
        help="Disable Kairos and OR-Tools progress logging.",
    )
    parser.add_argument(
        "--preview-lines",
        type=int,
        default=120,
        help="How many tracker lines to print to the terminal after writing the full log file.",
    )
    parser.add_argument(
        "--hide-idle",
        action="store_true",
        help="Skip idle/waiting lines in the tracker output.",
    )
    args = parser.parse_args()
    main(
        mode=args.mode,
        seed=args.seed,
        time_limit_seconds=args.time_limit,
        logging_enabled=not args.quiet_kairos,
        ortools_logging=not args.quiet_kairos,
        workers=args.workers,
        relative_gap_limit=args.relative_gap,
        absolute_gap_limit=args.absolute_gap,
        preview_lines=args.preview_lines,
        include_idle=not args.hide_idle,
    )
