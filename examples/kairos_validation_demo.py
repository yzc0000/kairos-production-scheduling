from __future__ import annotations

import argparse
import sys
from contextlib import ExitStack
from time import perf_counter
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = PROJECT_ROOT / "Kairos-Scheduler-main"

for path in (PROJECT_ROOT, KAIROS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import kairos as kr
from kairos.solvers import google_cp as kairos_google_cp

from factory_sim import KairosGanttVisualizer, SimulationGanttVisualizer, validate_kairos_solution


MACHINE_POOL_SPECS = (
    ("SAW", "Saw", 3, 45.0),
    ("PRESS", "Press", 2, 38.0),
    ("KAMSAN", "Kamsan", 2, 55.0),
    ("CNC", "CNC", 3, 62.0),
    ("BEARING", "Bearing Fastening", 2, 50.0),
    ("PIN", "Door Bolt Pin Machine", 2, 35.0),
    ("BODY", "Door Bolt Body Machine", 2, 35.0),
    ("BEAD", "Bead Machine", 2, 32.0),
    ("WELD", "Welding Machine", 3, 48.0),
    ("HILGELAND", "Hilgeland Machine", 2, 60.0),
    ("FRAME", "Frame or Bolt Machine", 2, 40.0),
    ("ASSEMBLY", "Assembly Worker", 4, 28.0),
    ("BOX", "Boxing Worker", 2, 22.0),
    ("PACK", "Packaging Worker", 2, 22.0),
    ("SHIP", "Shipping Line", 2, 18.0),
)

MARKETS = ("Domestic", "Iran", "Iraq", "Export")
DEMO_SOLVE_TIME_LIMIT_SECONDS = 30
DEMO_SOLVER_LOGGING_ENABLED = True
DEMO_ORTOOLS_LOGGING_ENABLED = True
DEMO_SOLVER_WORKERS: int | None = None
DEMO_RELATIVE_GAP_LIMIT: float | None = None
DEMO_ABSOLUTE_GAP_LIMIT: float | None = None


def build_large_demo_problem() -> "kr.SchedulingProblem":
    problem = kr.SchedulingProblem(name="Large Flexible Assembly Job Shop Validation Demo")
    machine_pools = _add_machine_pools(problem)

    job_builders = (
        ("bullet", _build_bullet_job, 8),
        ("wheel", _build_wheel_job, 8),
        ("slider", _build_slider_job, 8),
        ("hinge", _build_hinge_job, 8),
    )

    for family_offset, (family_key, builder, count) in enumerate(job_builders):
        for serial in range(1, count + 1):
            schedule_offset = (serial - 1) * 18 + family_offset * 7
            market = MARKETS[(serial + family_offset) % len(MARKETS)]
            builder(problem, machine_pools, serial, market, schedule_offset)

    return problem


def machine_names_for_problem(problem: "kr.SchedulingProblem") -> list[str]:
    return [machine.name or str(machine.id) for machine in problem.machines.values()]


def solve_large_demo_problem(
    time_limit_seconds: int = DEMO_SOLVE_TIME_LIMIT_SECONDS,
    *,
    logging_enabled: bool = DEMO_SOLVER_LOGGING_ENABLED,
    ortools_logging: bool = DEMO_ORTOOLS_LOGGING_ENABLED,
    workers: int | None = DEMO_SOLVER_WORKERS,
    relative_gap_limit: float | None = DEMO_RELATIVE_GAP_LIMIT,
    absolute_gap_limit: float | None = DEMO_ABSOLUTE_GAP_LIMIT,
) -> tuple["kr.SchedulingProblem", "kr.SolutionResult"]:
    problem = build_large_demo_problem()
    print("Kairos solve configuration:")
    print("  Time limit (seconds):", time_limit_seconds)
    print("  Workers:", workers if workers is not None else "system default")
    print("  Kairos logging:", logging_enabled)
    print("  OR-Tools progress logging:", ortools_logging)
    print(
        "  Relative gap limit:",
        relative_gap_limit if relative_gap_limit is not None else "disabled",
    )
    print(
        "  Absolute gap limit:",
        absolute_gap_limit if absolute_gap_limit is not None else "disabled",
    )

    original_cp_solver_class = kairos_google_cp.cp_model.CpSolver

    def _build_cp_solver():
        cp_solver = original_cp_solver_class()
        if relative_gap_limit is not None:
            cp_solver.parameters.relative_gap_limit = relative_gap_limit
        if absolute_gap_limit is not None:
            cp_solver.parameters.absolute_gap_limit = absolute_gap_limit
        return cp_solver

    with ExitStack() as patch_stack:
        if workers is not None:
            patch_stack.enter_context(
                patch("kairos.solvers.google_cp.os.cpu_count", return_value=workers)
            )
        if relative_gap_limit is not None or absolute_gap_limit is not None:
            patch_stack.enter_context(
                patch("kairos.solvers.google_cp.cp_model.CpSolver", side_effect=_build_cp_solver)
            )
        solver = kr.SolverFactory.get_solver(
            kr.SolverType.CP_SAT,
            logging_enabled=logging_enabled,
            ortools_logging=ortools_logging,
        )
        can_solve, message = solver.can_solve(problem)
        print("  Compatibility:", message)
        solve_started_at = perf_counter()
        solution = solver.solve(problem, time_limit_seconds=time_limit_seconds)
    print(f"Kairos solve finished in {perf_counter() - solve_started_at:.2f} seconds")
    return problem, solution


def _add_machine_pools(problem: "kr.SchedulingProblem") -> dict[str, list[str]]:
    machine_pools: dict[str, list[str]] = {}
    for prefix, display_name, count, hourly_cost in MACHINE_POOL_SPECS:
        machine_ids: list[str] = []
        for index in range(1, count + 1):
            machine_id = f"{prefix}-{index}"
            machine_name = f"{display_name} {index}"
            problem.add_machine(kr.Machine(id=machine_id, name=machine_name, hourly_cost=hourly_cost))
            machine_ids.append(machine_id)
        machine_pools[prefix] = machine_ids
    return machine_pools


def _build_bullet_job(
    problem: "kr.SchedulingProblem",
    machine_pools: dict[str, list[str]],
    serial: int,
    market: str,
    schedule_offset: int,
) -> None:
    job = kr.Job(
        id=f"BULLET-{serial}",
        name=f"{market} Bullet {serial}",
        due_date=schedule_offset + 230,
        priority=3 if market == "Export" else 2,
        task_type="Bullet",
    )

    saw_cut = _make_task(
        task_id=f"BULLET-{serial}-SAW",
        name="Iron Cut",
        task_type="Iron Cut",
        setup_time=15,
        machine_ids=machine_pools["SAW"],
        duration=18,
    )
    male_part = _make_task(
        task_id=f"BULLET-{serial}-MALE",
        name="Male Part",
        task_type="Male Part",
        setup_time=10,
        machine_ids=machine_pools["KAMSAN"],
        duration=16,
        predecessors=[saw_cut],
    )
    female_part = _make_task(
        task_id=f"BULLET-{serial}-FEMALE",
        name="Female Part",
        task_type="Female Part",
        setup_time=10,
        machine_ids=machine_pools["KAMSAN"],
        duration=16,
        predecessors=[saw_cut],
    )
    assembly = _make_task(
        task_id=f"BULLET-{serial}-ASM",
        name="Assembly",
        task_type="Bullet Assembly",
        setup_time=6,
        machine_ids=machine_pools["ASSEMBLY"],
        duration=26,
        predecessors=[male_part, female_part],
    )
    packaging = _make_task(
        task_id=f"BULLET-{serial}-PACK",
        name="Packaging",
        task_type="Bullet Packaging",
        setup_time=3,
        machine_ids=machine_pools["PACK"],
        duration=12,
        predecessors=[assembly],
    )
    shipping = _make_task(
        task_id=f"BULLET-{serial}-SHIP",
        name="Shipping",
        task_type="Bullet Shipping",
        setup_time=2,
        machine_ids=machine_pools["SHIP"],
        duration=9,
        predecessors=[packaging],
    )

    for task in (saw_cut, male_part, female_part, assembly, packaging, shipping):
        job.add_task(task)
    problem.add_job(job)


def _build_wheel_job(
    problem: "kr.SchedulingProblem",
    machine_pools: dict[str, list[str]],
    serial: int,
    market: str,
    schedule_offset: int,
) -> None:
    job = kr.Job(
        id=f"WHEEL-{serial}",
        name=f"{market} Wheel {serial}",
        due_date=schedule_offset + 260,
        priority=2,
        task_type="Wheel",
    )

    saw_cut = _make_task(
        task_id=f"WHEEL-{serial}-SAW",
        name="Wheel Cut",
        task_type="Wheel Cut",
        setup_time=10,
        machine_ids=machine_pools["SAW"],
        duration=14,
    )
    press_blank = _make_task(
        task_id=f"WHEEL-{serial}-PRESS",
        name="Metal Shavings",
        task_type="Metal Shavings",
        setup_time=8,
        machine_ids=machine_pools["PRESS"],
        duration=11,
    )
    cnc_turn = _make_task(
        task_id=f"WHEEL-{serial}-CNC",
        name="Wheel CNC",
        task_type="Wheel CNC",
        setup_time=12,
        machine_ids=machine_pools["CNC"],
        duration=18,
        predecessors=[saw_cut],
    )
    bearing = _make_task(
        task_id=f"WHEEL-{serial}-BEARING",
        name="Bearing Fastening",
        task_type="Bear Fasten",
        setup_time=6,
        machine_ids=machine_pools["BEARING"],
        duration=13,
        predecessors=[cnc_turn],
    )
    assembly = _make_task(
        task_id=f"WHEEL-{serial}-ASM",
        name="Assembly",
        task_type="Wheel Assembly",
        setup_time=8,
        machine_ids=machine_pools["ASSEMBLY"],
        duration=34,
        predecessors=[bearing, press_blank],
    )
    packaging = _make_task(
        task_id=f"WHEEL-{serial}-PACK",
        name="Packaging",
        task_type="Wheel Packaging",
        setup_time=4,
        machine_ids=machine_pools["PACK"],
        duration=13,
        predecessors=[assembly],
    )
    shipping = _make_task(
        task_id=f"WHEEL-{serial}-SHIP",
        name="Shipping",
        task_type="Wheel Shipping",
        setup_time=3,
        machine_ids=machine_pools["SHIP"],
        duration=10,
        predecessors=[packaging],
    )

    for task in (saw_cut, press_blank, cnc_turn, bearing, assembly, packaging, shipping):
        job.add_task(task)
    problem.add_job(job)


def _build_slider_job(
    problem: "kr.SchedulingProblem",
    machine_pools: dict[str, list[str]],
    serial: int,
    market: str,
    schedule_offset: int,
) -> None:
    job = kr.Job(
        id=f"SLIDER-{serial}",
        name=f"{market} Slider {serial}",
        due_date=schedule_offset + 250,
        priority=2,
        task_type="Slider",
    )

    pin_form = _make_task(
        task_id=f"SLIDER-{serial}-PIN",
        name="Pin",
        task_type="Pin",
        setup_time=4,
        machine_ids=machine_pools["PIN"],
        duration=9,
    )
    body_form = _make_task(
        task_id=f"SLIDER-{serial}-BODY",
        name="Body",
        task_type="Body",
        setup_time=4,
        machine_ids=machine_pools["BODY"],
        duration=10,
    )
    bead_make = _make_task(
        task_id=f"SLIDER-{serial}-BEAD",
        name="Beads",
        task_type="Beads",
        setup_time=8,
        machine_ids=machine_pools["BEAD"],
        duration=12,
    )
    welding = _make_task(
        task_id=f"SLIDER-{serial}-WELD",
        name="Welding",
        task_type="Welding",
        setup_time=6,
        machine_ids=machine_pools["WELD"],
        duration=16,
        predecessors=[body_form, bead_make],
    )
    assembly = _make_task(
        task_id=f"SLIDER-{serial}-ASM",
        name="Assembly",
        task_type="Slider Assembly",
        setup_time=7,
        machine_ids=machine_pools["ASSEMBLY"],
        duration=22,
        predecessors=[pin_form, welding],
    )
    boxing = _make_task(
        task_id=f"SLIDER-{serial}-BOX",
        name="Boxing",
        task_type="Slider Boxing",
        setup_time=3,
        machine_ids=machine_pools["BOX"],
        duration=9,
        predecessors=[assembly],
    )
    packaging = _make_task(
        task_id=f"SLIDER-{serial}-PACK",
        name="Packaging",
        task_type="Slider Packaging",
        setup_time=3,
        machine_ids=machine_pools["PACK"],
        duration=11,
        predecessors=[boxing],
    )

    for task in (pin_form, body_form, bead_make, welding, assembly, boxing, packaging):
        job.add_task(task)
    problem.add_job(job)


def _build_hinge_job(
    problem: "kr.SchedulingProblem",
    machine_pools: dict[str, list[str]],
    serial: int,
    market: str,
    schedule_offset: int,
) -> None:
    job = kr.Job(
        id=f"HINGE-{serial}",
        name=f"{market} Hinge {serial}",
        due_date=schedule_offset + 220,
        priority=1,
        task_type="Hinge",
    )

    wing_frame = _make_task(
        task_id=f"HINGE-{serial}-WING",
        name="Wing",
        task_type="Wing",
        setup_time=4,
        machine_ids=machine_pools["FRAME"],
        duration=11,
    )
    hinge_pin = _make_task(
        task_id=f"HINGE-{serial}-PIN",
        name="Pin",
        task_type="Pin",
        setup_time=3,
        machine_ids=machine_pools["HILGELAND"],
        duration=10,
    )
    assembly = _make_task(
        task_id=f"HINGE-{serial}-ASM",
        name="Assembly",
        task_type="Hinge Assembly",
        setup_time=5,
        machine_ids=machine_pools["ASSEMBLY"],
        duration=17,
        predecessors=[wing_frame, hinge_pin],
    )
    boxing = _make_task(
        task_id=f"HINGE-{serial}-BOX",
        name="Boxing",
        task_type="Hinge Boxing",
        setup_time=2,
        machine_ids=machine_pools["BOX"],
        duration=7,
        predecessors=[assembly],
    )
    packaging = _make_task(
        task_id=f"HINGE-{serial}-PACK",
        name="Packaging",
        task_type="Hinge Packaging",
        setup_time=2,
        machine_ids=machine_pools["PACK"],
        duration=8,
        predecessors=[boxing],
    )

    for task in (wing_frame, hinge_pin, assembly, boxing, packaging):
        job.add_task(task)
    problem.add_job(job)


def _make_task(
    task_id: str,
    name: str,
    task_type: str,
    setup_time: int,
    machine_ids: list[str],
    duration: int,
    release_time: int = 0,
    predecessors: list["kr.Task"] | None = None,
) -> "kr.Task":
    task = kr.Task(id=task_id, name=name, task_type=task_type, setup_time=setup_time, release_time=release_time)
    for machine_id in machine_ids:
        task.add_alternative(machine_id, duration)
    for predecessor in predecessors or []:
        task.add_predecessor(predecessor)
    return task


def _summarize_problem(problem: "kr.SchedulingProblem") -> dict[str, int]:
    return {
        "machines": len(problem.machines),
        "jobs": len(problem.jobs),
        "tasks": len(problem.tasks),
    }


def _print_report(problem: "kr.SchedulingProblem", solution: "kr.SolutionResult", report) -> None:
    summary = _summarize_problem(problem)
    print("Problem:", problem.name)
    print("Machines:", summary["machines"])
    print("Jobs:", summary["jobs"])
    print("Tasks:", summary["tasks"])
    print("Kairos status:", solution.status)
    print("Objective value:", solution.objective_value)
    print("Exact match:", report.exact_match)
    print("Planned makespan:", report.planned_makespan)
    print("Actual makespan:", report.actual_makespan)
    print("Makespan delta:", report.makespan_delta)

    mismatches = [operation for operation in report.operation_validations if not operation.matches_exactly]
    print("Mismatched operations:", len(mismatches))
    for operation in mismatches[:15]:
        print(
            operation.operation_id,
            operation.machine_id,
            "planned:",
            (operation.planned_start, operation.planned_end),
            "actual:",
            (operation.actual_start, operation.actual_end),
            "delta:",
            (operation.start_delta, operation.end_delta),
        )


def main(
    *,
    time_limit_seconds: int = DEMO_SOLVE_TIME_LIMIT_SECONDS,
    logging_enabled: bool = DEMO_SOLVER_LOGGING_ENABLED,
    ortools_logging: bool = DEMO_ORTOOLS_LOGGING_ENABLED,
    workers: int | None = DEMO_SOLVER_WORKERS,
    relative_gap_limit: float | None = DEMO_RELATIVE_GAP_LIMIT,
    absolute_gap_limit: float | None = DEMO_ABSOLUTE_GAP_LIMIT,
) -> None:
    problem, solution = solve_large_demo_problem(
        time_limit_seconds=time_limit_seconds,
        logging_enabled=logging_enabled,
        ortools_logging=ortools_logging,
        workers=workers,
        relative_gap_limit=relative_gap_limit,
        absolute_gap_limit=absolute_gap_limit,
    )
    report = validate_kairos_solution(problem, solution, trace=False)
    machine_names = machine_names_for_problem(problem)

    output_dir = PROJECT_ROOT / "examples" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    kairos_html_path = output_dir / "large_kairos_validation_schedule.html"
    sim_html_path = output_dir / "large_sim_validation_schedule.html"
    comparison_html_path = output_dir / "large_schedule_comparison.html"

    KairosGanttVisualizer(color_by="job_family").save_html(
        solution,
        str(kairos_html_path),
        title=f"{problem.name} - Kairos",
        machine_names=machine_names,
    )
    SimulationGanttVisualizer(color_by="family_id").save_html(
        result=report.simulation_result,
        schedule_bundle=report.schedule_bundle,
        file_path=str(sim_html_path),
        title=f"{problem.name} - Simulation",
    )
    _write_comparison_page(
        comparison_html_path=comparison_html_path,
        kairos_html_path=kairos_html_path,
        sim_html_path=sim_html_path,
        report=report,
        problem_name=problem.name,
    )

    _print_report(problem, solution, report)
    print("Kairos HTML:", kairos_html_path)
    print("Simulation HTML:", sim_html_path)
    print("Comparison HTML:", comparison_html_path)


def _write_comparison_page(
    comparison_html_path: Path,
    kairos_html_path: Path,
    sim_html_path: Path,
    report,
    problem_name: str,
) -> None:
    actual_makespan_text = "N/A" if report.actual_makespan is None else f"{report.actual_makespan:.2f}"
    makespan_delta_text = "N/A" if report.makespan_delta is None else f"{report.makespan_delta:.2f}"
    comparison_html_path.write_text(
        "\n".join(
            [
                "<!DOCTYPE html>",
                "<html lang=\"en\">",
                "<head>",
                "  <meta charset=\"utf-8\">",
                f"  <title>{problem_name} - Kairos vs Simulation</title>",
                "  <style>",
                "    body { font-family: Segoe UI, Arial, sans-serif; margin: 0; padding: 24px; background: #f4f6f8; color: #111827; }",
                "    h1, h2, p { margin: 0 0 12px; }",
                "    .summary { background: white; border-radius: 12px; padding: 16px 18px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(15, 23, 42, 0.08); }",
                "    .links { margin-top: 10px; }",
                "    .links a { margin-right: 16px; }",
                "    iframe { width: 100%; height: 950px; border: 1px solid #cbd5e1; border-radius: 12px; background: white; margin-bottom: 24px; }",
                "  </style>",
                "</head>",
                "<body>",
                f"  <div class=\"summary\"><h1>{problem_name} - Kairos vs Simulation</h1>",
                f"  <p>Exact match: {report.exact_match} | Planned makespan: {report.planned_makespan:.2f} | Actual makespan: {actual_makespan_text} | Makespan delta: {makespan_delta_text}</p>",
                "  <div class=\"links\">",
                f"    <a href=\"{kairos_html_path.name}\">Open Kairos chart</a>",
                f"    <a href=\"{sim_html_path.name}\">Open simulation chart</a>",
                "  </div></div>",
                "  <h2>Kairos Schedule</h2>",
                f"  <iframe src=\"{kairos_html_path.name}\"></iframe>",
                "  <h2>Simulation Schedule</h2>",
                f"  <iframe src=\"{sim_html_path.name}\"></iframe>",
                "</body>",
                "</html>",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the large Kairos-to-simulation validation demo.")
    parser.add_argument(
        "--time-limit",
        type=int,
        default=DEMO_SOLVE_TIME_LIMIT_SECONDS,
        help="Kairos CP-SAT time limit in seconds.",
    )
    parser.add_argument(
        "--quiet-kairos",
        action="store_true",
        help="Disable Kairos and OR-Tools progress logging.",
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
        help="Stop early when the relative optimality gap drops below this value, e.g. 0.05 for 5%%.",
    )
    parser.add_argument(
        "--absolute-gap",
        type=float,
        default=None,
        help="Stop early when the absolute objective gap drops below this value.",
    )
    args = parser.parse_args()
    main(
        time_limit_seconds=args.time_limit,
        logging_enabled=not args.quiet_kairos,
        ortools_logging=not args.quiet_kairos,
        workers=args.workers,
        relative_gap_limit=args.relative_gap,
        absolute_gap_limit=args.absolute_gap,
    )
