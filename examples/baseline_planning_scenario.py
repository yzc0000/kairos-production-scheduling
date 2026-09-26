from __future__ import annotations

import argparse
import statistics
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = PROJECT_ROOT / "Kairos-Scheduler-main"

for path in (PROJECT_ROOT, KAIROS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import kairos as kr

from factory_sim import (
    KairosGanttVisualizer,
    SimulationGanttVisualizer,
    build_distribution,
    build_failure_profile,
    build_schedule_bundle,
    build_schedule_bundle_from_kairos,
    run_week,
)

SCENARIOS = ("baseline", "cnc_breakdown", "assembly_slowdown")


def build_problem() -> "kr.SchedulingProblem":
    """Small stochastic what-if baseline: 5 jobs, shared resources, joins, due dates."""
    problem = kr.SchedulingProblem(name="Door Hardware What-If Planning Scenario")

    machine_specs = [
        ("CUT-1", "Cutting Saw 1", 35.0),
        ("CUT-2", "Cutting Saw 2", 35.0),
        ("CNC-1", "CNC Cell 1", 60.0),
        ("CNC-2", "CNC Cell 2", 60.0),
        ("CNC-3", "CNC Cell 3", 60.0),
        ("PRESS-1", "Press 1", 45.0),
        ("ASM-1", "Assembly Station 1", 30.0),
        ("ASM-2", "Assembly Station 2", 30.0),
        ("PACK-1", "Packaging Station", 20.0),
    ]
    for machine_id, name, hourly_cost in machine_specs:
        problem.add_machine(kr.Machine(id=machine_id, name=name, hourly_cost=hourly_cost))

    job_specs = (
        ("EXPORT-LOCK", "Export Lock Batch", "Lock", 95, 5, (12, 22, 16, 18, 8)),
        ("DOM-LOCK", "Domestic Lock Batch", "Lock", 115, 2, (10, 18, 14, 16, 7)),
        ("EXPORT-HINGE", "Export Hinge Batch", "Hinge", 105, 4, (9, 20, 12, 15, 6)),
        ("SPARE-BOLT", "Spare Bolt Batch", "Bolt", 140, 1, (8, 14, 10, 12, 5)),
        ("URGENT-KIT", "Urgent Service Kit", "Kit", 90, 6, (7, 16, 11, 14, 6)),
    )

    for job_id, name, family, due_date, priority, durations in job_specs:
        cut_time, cnc_time, press_time, assembly_time, pack_time = durations
        job = kr.Job(
            id=job_id,
            name=name,
            due_date=due_date,
            priority=priority,
            task_type=family,
        )

        cut = _task(f"{job_id}-CUT", "Cut raw material", f"{family}-cut", 4)
        for machine_id in ("CUT-1", "CUT-2"):
            cut.add_alternative(machine_id, cut_time)

        cnc = _task(f"{job_id}-CNC", "CNC machining", f"{family}-cnc", 7)
        for machine_id in ("CNC-1", "CNC-2", "CNC-3"):
            cnc.add_alternative(machine_id, cnc_time)
        cnc.add_predecessor(cut)

        press = _task(f"{job_id}-PRESS", "Press forming", f"{family}-press", 5)
        press.add_alternative("PRESS-1", press_time)
        press.add_predecessor(cut)

        assembly = _task(f"{job_id}-ASM", "Final assembly", f"{family}-assembly", 6)
        for machine_id in ("ASM-1", "ASM-2"):
            assembly.add_alternative(machine_id, assembly_time)
        assembly.add_predecessor(cnc)
        assembly.add_predecessor(press)

        packaging = _task(f"{job_id}-PACK", "Packaging", f"{family}-pack", 2)
        packaging.add_alternative("PACK-1", pack_time)
        packaging.add_predecessor(assembly)

        for task in (cut, cnc, press, assembly, packaging):
            job.add_task(task)
        problem.add_job(job)

    return problem


def _task(task_id: str, name: str, task_type: str, setup_time: int) -> "kr.Task":
    return kr.Task(id=task_id, name=name, task_type=task_type, setup_time=setup_time)


def solve_problem(
    problem: "kr.SchedulingProblem",
    objective: "kr.ObjectiveType",
    time_limit_seconds: int,
) -> "kr.SolutionResult":
    solver = kr.SolverFactory.get_solver(
        kr.SolverType.CP_SAT,
        objective_type=objective,
        logging_enabled=False,
        ortools_logging=False,
    )
    solution = solver.solve(problem, time_limit_seconds=time_limit_seconds)
    if not solution.is_success:
        raise RuntimeError(f"Kairos failed to solve what-if problem: {solution.status}")
    return solution


def run_what_if(
    *,
    scenario: str,
    objective: "kr.ObjectiveType",
    time_limit_seconds: int,
    replications: int,
    seed: int,
) -> None:
    problem = build_problem()
    solution = solve_problem(problem, objective, time_limit_seconds)
    conversion = build_schedule_bundle_from_kairos(problem, solution, horizon_padding=260.0)
    bundle = _build_stochastic_bundle(conversion.schedule_bundle, scenario)

    rows = []
    representative_result = None
    representative_seed = seed

    for index in range(replications):
        current_seed = seed + index
        result = run_week(
            bundle,
            seed=current_seed,
            hooks=conversion.hooks,
            trace=index == 0,
        )
        if representative_result is None:
            representative_result = result
            representative_seed = current_seed
        rows.append(_build_replication_row(problem, solution, result, current_seed))

    if representative_result is None:
        raise RuntimeError("No simulation replications were executed.")

    output_paths = write_visualizations(
        problem=problem,
        solution=solution,
        bundle=bundle,
        result=representative_result,
        scenario=scenario,
        seed=representative_seed,
    )
    print_scenario_report(
        problem=problem,
        solution=solution,
        bundle=bundle,
        representative_result=representative_result,
        scenario=scenario,
        rows=rows,
        output_paths=output_paths,
        representative_seed=representative_seed,
    )


def _build_stochastic_bundle(bundle, scenario: str):
    target_breakdown_machine = _busiest_machine(bundle, prefix="CNC-") if scenario == "cnc_breakdown" else None

    machines = []
    for machine in bundle.machines.values():
        failure_profile = machine.failure_profile
        if machine.machine_id == target_breakdown_machine:
            failure_profile = build_failure_profile(
                profile_id="what_if_cnc_breakdown",
                uptime_distribution=build_distribution("exponential", mean=18.0),
                repair_distribution=build_distribution("triangular", low=10.0, mode=18.0, high=28.0),
            )
        machines.append(replace(machine, failure_profile=failure_profile))

    batches = []
    for batch in bundle.batches.values():
        route = []
        for step in batch.route:
            base_duration = float(step.process_time_per_unit.parameters.get("value", 0.0))
            process_distribution = _stochastic_process_distribution(
                base_duration,
                scenario=scenario,
                step_id=step.step_id,
            )
            route.append(
                replace(
                    step,
                    process_time_per_unit=process_distribution,
                    metadata={
                        **step.metadata,
                        "deterministic_base_duration": base_duration,
                        "stochastic_scenario": scenario,
                    },
                )
            )
        batches.append(replace(batch, route=tuple(route)))

    return build_schedule_bundle(
        week_horizon=bundle.week_horizon,
        machines=machines,
        batches=batches,
        schedule_operations=bundle.schedule_operations,
        basket_rules=bundle.basket_rules.values(),
        travel_matrix=bundle.travel_matrix,
        metadata={
            **bundle.metadata,
            "scenario": scenario,
            "breakdown_target_machine_id": target_breakdown_machine,
            "process_time_model": _process_time_model_label(scenario),
        },
    )


def _stochastic_process_distribution(base_duration: float, *, scenario: str, step_id: str):
    if base_duration <= 0:
        return build_distribution("deterministic", value=0.0)
    if scenario == "assembly_slowdown" and step_id.endswith("-ASM"):
        return build_distribution(
            "triangular",
            low=base_duration * 1.10,
            mode=base_duration * 1.30,
            high=base_duration * 1.65,
        )
    return build_distribution(
        "triangular",
        low=max(0.1, base_duration * 0.85),
        mode=base_duration,
        high=base_duration * 1.30,
    )


def _process_time_model_label(scenario: str) -> str:
    if scenario == "assembly_slowdown":
        return "assembly triangular(1.10x, 1.30x, 1.65x), others triangular(0.85x, 1.00x, 1.30x)"
    return "triangular(0.85x, 1.00x, 1.30x)"


def _busiest_machine(bundle, *, prefix: str) -> str | None:
    load_by_machine: dict[str, float] = {}
    for operation in bundle.schedule_operations:
        if operation.machine_id.startswith(prefix):
            load_by_machine[operation.machine_id] = load_by_machine.get(
                operation.machine_id,
                0.0,
            ) + (operation.planned_end - operation.planned_start)
    if not load_by_machine:
        return None
    return max(load_by_machine, key=load_by_machine.get)


def _build_replication_row(problem, solution, result, seed: int) -> dict[str, float | int | bool | None]:
    completed_ops = [operation for operation in result.operations if operation.actual_end is not None]
    makespan = max((operation.actual_end for operation in completed_ops), default=None)
    weighted_tardiness = _actual_weighted_tardiness(problem, result)
    planned_makespan = float(solution.makespan or 0.0)
    return {
        "seed": seed,
        "makespan": makespan,
        "makespan_delta": None if makespan is None else makespan - planned_makespan,
        "weighted_tardiness": weighted_tardiness,
        "completed_batches": len([batch for batch in result.batch_summaries if batch.completed]),
        "leftover_batches": len(result.leftover_batches),
        "total_downtime": sum(machine.downtime_time for machine in result.machine_summaries),
        "delay_flag": bool(
            result.leftover_batches
            or (makespan is not None and makespan > planned_makespan * 1.10)
        ),
    }


def print_scenario_report(
    *,
    problem,
    solution,
    bundle,
    representative_result,
    scenario: str,
    rows: list[dict[str, float | int | bool | None]],
    output_paths: dict[str, Path],
    representative_seed: int,
) -> None:
    makespans = [float(row["makespan"]) for row in rows if row["makespan"] is not None]
    makespan_deltas = [
        float(row["makespan_delta"]) for row in rows if row["makespan_delta"] is not None
    ]
    tardiness_values = [float(row["weighted_tardiness"]) for row in rows]
    downtime_values = [float(row["total_downtime"]) for row in rows]
    completed_batch_values = [float(row["completed_batches"]) for row in rows]
    leftover_batch_values = [float(row["leftover_batches"]) for row in rows]
    completed_all_count = len([row for row in rows if int(row["leftover_batches"]) == 0])
    delay_count = len([row for row in rows if row["delay_flag"]])

    mean_makespan = statistics.fmean(makespans) if makespans else None
    mean_makespan_delta = statistics.fmean(makespan_deltas) if makespan_deltas else None
    ci_low, ci_high = _confidence_interval(makespans)
    mean_tardiness = statistics.fmean(tardiness_values) if tardiness_values else 0.0
    mean_downtime = statistics.fmean(downtime_values) if downtime_values else 0.0
    mean_completed_batches = (
        statistics.fmean(completed_batch_values) if completed_batch_values else 0.0
    )
    mean_leftover_batches = statistics.fmean(leftover_batch_values) if leftover_batch_values else 0.0

    print("")
    print("=== Stochastic What-If Scenario ===")
    print(f"Scenario: {scenario}")
    print(f"Jobs: {len(problem.jobs)} | Tasks: {len(problem.tasks)} | Machines: {len(problem.machines)}")
    print(f"Replications: {len(rows)}")
    print(f"CP status: {solution.status}")
    print(f"CP objective value: {solution.objective_value}")
    print(f"CP makespan: {solution.makespan}")
    print(f"CP weighted tardiness: {solution.weighted_tardiness}")
    print(f"Mean simulated makespan: {_fmt(mean_makespan)}")
    print(f"Mean makespan delta vs CP: {_fmt(mean_makespan_delta)}")
    print(f"95% CI for makespan: [{_fmt(ci_low)}, {_fmt(ci_high)}]")
    print(f"Mean simulated weighted tardiness: {mean_tardiness:.2f}")
    print(f"Mean total downtime: {mean_downtime:.2f}")
    print(f"Mean completed batches: {mean_completed_batches:.2f}/{len(problem.jobs)}")
    print(f"Mean leftover batches: {mean_leftover_batches:.2f}")
    print(f"Completed-all rate: {_safe_pct(completed_all_count, len(rows)):.1f}%")
    print(f"Delay-risk rate: {_safe_pct(delay_count, len(rows)):.1f}%")
    if bundle.metadata.get("breakdown_target_machine_id"):
        print(f"Breakdown target: {bundle.metadata['breakdown_target_machine_id']}")
    print(f"Representative seed: {representative_seed}")
    print(f"Kairos HTML: {output_paths['kairos']}")
    print(f"Simulation HTML: {output_paths['simulation']}")
    print(f"Comparison HTML: {output_paths['comparison']}")

    print("")
    print("Representative-run machine utilization")
    print("machine        active%  productive%  setup  downtime  idle  completed")
    representative_makespan = max(
        (operation.actual_end for operation in representative_result.operations if operation.actual_end is not None),
        default=bundle.week_horizon,
    )
    for machine in sorted(representative_result.machine_summaries, key=lambda item: item.machine_id):
        active_time = machine.productive_time + machine.setup_time
        print(
            f"{machine.machine_id:<12}"
            f"{_safe_pct(active_time, representative_makespan):>7.1f}"
            f"{_safe_pct(machine.productive_time, representative_makespan):>12.1f}"
            f"{machine.setup_time:>7.1f}"
            f"{machine.downtime_time:>10.1f}"
            f"{machine.idle_time:>6.1f}"
            f"{machine.completed_operations:>10}"
        )

    print("")
    print("Planning interpretation")
    print(_planning_interpretation(solution, mean_makespan, mean_tardiness, completed_all_count, delay_count, rows))


def write_visualizations(problem, solution, bundle, result, scenario: str, seed: int) -> dict[str, Path]:
    output_dir = PROJECT_ROOT / "examples" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    kairos_path = output_dir / f"what_if_{scenario}_kairos.html"
    simulation_path = output_dir / f"what_if_{scenario}_simulation_seed_{seed}.html"
    comparison_path = output_dir / f"what_if_{scenario}_comparison.html"

    machine_names = [machine.name or str(machine.id) for machine in problem.machines.values()]
    KairosGanttVisualizer(color_by="job_family").save_html(
        solution,
        str(kairos_path),
        title=f"{problem.name} - CP Plan ({scenario})",
        machine_names=machine_names,
    )
    SimulationGanttVisualizer(color_by="family_id").save_html(
        result=result,
        schedule_bundle=bundle,
        file_path=str(simulation_path),
        title=f"{problem.name} - Stochastic Simulation ({scenario}, seed {seed})",
    )
    _write_comparison_html(
        comparison_path=comparison_path,
        kairos_path=kairos_path,
        simulation_path=simulation_path,
        problem_name=problem.name,
        scenario=scenario,
        seed=seed,
    )
    return {
        "kairos": kairos_path,
        "simulation": simulation_path,
        "comparison": comparison_path,
    }


def _write_comparison_html(
    *,
    comparison_path: Path,
    kairos_path: Path,
    simulation_path: Path,
    problem_name: str,
    scenario: str,
    seed: int,
) -> None:
    comparison_path.write_text(
        "\n".join(
            [
                "<!DOCTYPE html>",
                "<html lang=\"en\">",
                "<head>",
                "  <meta charset=\"utf-8\">",
                f"  <title>{problem_name} - {scenario}</title>",
                "  <style>",
                "    body { font-family: Segoe UI, Arial, sans-serif; margin: 0; padding: 24px; background: #f4f6f8; color: #111827; }",
                "    h1, h2, p { margin: 0 0 12px; }",
                "    .summary { background: white; border-radius: 12px; padding: 16px 18px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(15, 23, 42, 0.08); }",
                "    .links { margin-top: 10px; }",
                "    .links a { margin-right: 16px; }",
                "    iframe { width: 100%; height: 900px; border: 1px solid #cbd5e1; border-radius: 12px; background: white; margin-bottom: 24px; }",
                "  </style>",
                "</head>",
                "<body>",
                f"  <div class=\"summary\"><h1>{problem_name}</h1>",
                f"  <p>Scenario: {scenario} | Representative seed: {seed}</p>",
                "  <div class=\"links\">",
                f"    <a href=\"{kairos_path.name}\">Open CP plan</a>",
                f"    <a href=\"{simulation_path.name}\">Open stochastic simulation</a>",
                "  </div></div>",
                "  <h2>CP Plan</h2>",
                f"  <iframe src=\"{kairos_path.name}\"></iframe>",
                "  <h2>Stochastic Simulation</h2>",
                f"  <iframe src=\"{simulation_path.name}\"></iframe>",
                "</body>",
                "</html>",
            ]
        ),
        encoding="utf-8",
    )


def _actual_weighted_tardiness(problem, result) -> float:
    actual_end_by_operation = {
        operation.operation_id: operation.actual_end
        for operation in result.operations
        if operation.actual_end is not None
    }
    total = 0.0
    for job in problem.jobs:
        if job.due_date is None:
            continue
        task_end_times = [
            actual_end_by_operation[str(task.id)]
            for task in job.tasks
            if str(task.id) in actual_end_by_operation
        ]
        if not task_end_times:
            continue
        completion = max(task_end_times)
        total += max(0.0, completion - float(job.due_date)) * float(job.priority)
    return total


def _confidence_interval(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    mean = statistics.fmean(values)
    stdev = statistics.stdev(values)
    margin = 1.96 * stdev / (len(values) ** 0.5)
    return mean - margin, mean + margin


def _planning_interpretation(
    solution,
    mean_makespan: float | None,
    mean_tardiness: float,
    completed_all_count: int,
    delay_count: int,
    rows: list[dict[str, float | int | bool | None]],
) -> str:
    if mean_makespan is None:
        return "Reject: simulations did not produce usable completion times."
    if completed_all_count < len(rows):
        return "Reject or replan: at least one stochastic replication leaves unfinished batches."
    if delay_count / len(rows) > 0.25:
        return "Review before release: more than 25% of replications exceed the delay threshold."
    if mean_makespan > float(solution.makespan or 0.0) * 1.10:
        return "Review before release: average simulated makespan is more than 10% above the CP plan."
    if mean_tardiness > float(solution.weighted_tardiness or 0.0):
        return "Review due-date risk: stochastic execution increases weighted tardiness versus the CP plan."
    return "Scenario is acceptable under the current stochastic assumptions."


def _safe_pct(numerator: float, denominator: float) -> float:
    return 0.0 if abs(denominator) < 1e-9 else numerator / denominator * 100.0


def _fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run stochastic what-if planning scenarios for CP schedules."
    )
    parser.add_argument(
        "--objective",
        choices=("makespan", "weighted-tardiness"),
        default="makespan",
        help="CP objective used to create the plan before stochastic simulation.",
    )
    parser.add_argument(
        "--scenario",
        choices=(*SCENARIOS, "all"),
        default="all",
        help="Which what-if scenario to run.",
    )
    parser.add_argument("--seed", type=int, default=7, help="First simulation random seed.")
    parser.add_argument("--replications", type=int, default=50, help="Number of stochastic replications.")
    parser.add_argument("--time-limit", type=int, default=20, help="CP-SAT time limit in seconds.")
    args = parser.parse_args()

    if args.replications <= 0:
        raise ValueError("--replications must be positive.")

    objective = (
        kr.ObjectiveType.WEIGHTED_TARDINESS
        if args.objective == "weighted-tardiness"
        else kr.ObjectiveType.MAKESPAN
    )

    scenarios = SCENARIOS if args.scenario == "all" else (args.scenario,)
    for scenario in scenarios:
        run_what_if(
            scenario=scenario,
            objective=objective,
            time_limit_seconds=args.time_limit,
            replications=args.replications,
            seed=args.seed,
        )


if __name__ == "__main__":
    main()
