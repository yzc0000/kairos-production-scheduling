from __future__ import annotations

import argparse
import pickle
import sys
from dataclasses import replace
from math import hypot
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = PROJECT_ROOT / "Kairos-Scheduler-main"

for path in (PROJECT_ROOT, KAIROS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from factory_sim import (
    Calendar,
    InitialMachineState,
    InitialOperationState,
    InitialSimulationState,
    KairosGanttVisualizer,
    SimulationGanttVisualizer,
    SimulationHooks,
    TimeWindow,
    build_distribution,
    build_failure_profile,
    build_kairos_validation_hooks,
    build_schedule_bundle,
    build_schedule_bundle_from_kairos,
    build_travel_matrix,
    run_week,
)
from factory_sim.hooks import default_process_time_hook
from examples.kairos_validation_demo import (
    DEMO_ABSOLUTE_GAP_LIMIT,
    DEMO_ORTOOLS_LOGGING_ENABLED,
    DEMO_RELATIVE_GAP_LIMIT,
    DEMO_SOLVE_TIME_LIMIT_SECONDS,
    DEMO_SOLVER_LOGGING_ENABLED,
    DEMO_SOLVER_WORKERS,
    machine_names_for_problem,
    solve_large_demo_problem,
)


LAYOUT_BY_MACHINE_GROUP = {
    "SAW": (0.0, 0.0),
    "PRESS": (0.5, 1.0),
    "KAMSAN": (2.0, 0.0),
    "CNC": (3.5, 1.0),
    "BEARING": (4.5, 1.0),
    "PIN": (0.0, 5.0),
    "BODY": (0.8, 5.8),
    "BEAD": (1.5, 6.5),
    "WELD": (2.8, 6.0),
    "FRAME": (0.0, 8.5),
    "HILGELAND": (1.4, 8.5),
    "ASSEMBLY": (6.0, 4.0),
    "BOX": (7.4, 4.8),
    "PACK": (8.6, 4.2),
    "SHIP": (10.0, 4.2),
}

FAILURE_CONFIG_BY_MACHINE_GROUP = {
    "SAW": (190.0, 14.0),
    "PRESS": (220.0, 12.0),
    "KAMSAN": (175.0, 16.0),
    "CNC": (235.0, 18.0),
    "BEARING": (250.0, 14.0),
    "WELD": (205.0, 15.0),
}

DEFAULT_START_HOUR_OFFSET = 0.0
PRODUCTION_PAUSE_DURATION = 20.0
ASSEMBLY_PAUSE_DURATION = 4.0
CRITICAL_OPERATION_PAUSE_ID = None
CRITICAL_OPERATION_PAUSE_DURATION = 0.0
COMPLETION_HORIZON_PADDING = 168.0
MAX_COMPLETION_HORIZON_ATTEMPTS = 6
FIXED_KAIROS_SOLUTION_PATH = PROJECT_ROOT / "examples" / "output" / "fixed_kairos_solution.pkl"


def build_stochastic_execution_bundle(base_bundle):
    stochastic_machines = [
        replace(
            machine,
            failure_profile=_build_failure_profile(machine.machine_id),
            metadata={
                **machine.metadata,
                "stochastic_demo": True,
            },
        )
        for machine in base_bundle.machines.values()
    ]

    stochastic_batches = []
    for batch in base_bundle.batches.values():
        stochastic_route = []
        for route_step in batch.route:
            deterministic_base = float(route_step.process_time_per_unit.parameters.get("value", 0.0))
            stochastic_route.append(
                replace(
                    route_step,
                    process_time_per_unit=_build_process_distribution(
                        family_id=batch.family_id or batch.product_id,
                        task_name=str(route_step.metadata.get("task_name") or route_step.name or route_step.step_id),
                        base_duration=deterministic_base,
                    ),
                    metadata={
                        **route_step.metadata,
                        "deterministic_base_duration": deterministic_base,
                    },
                )
            )
        stochastic_batches.append(replace(batch, route=tuple(stochastic_route)))

    stochastic_bundle = build_schedule_bundle(
        week_horizon=base_bundle.week_horizon,
        machines=stochastic_machines,
        batches=stochastic_batches,
        schedule_operations=base_bundle.schedule_operations,
        basket_rules=base_bundle.basket_rules.values(),
        travel_matrix=_build_layout_travel_matrix(base_bundle),
        metadata={
            **base_bundle.metadata,
            "scenario": "stochastic_execution_demo",
        },
    )
    return stochastic_bundle


def build_stochastic_execution_hooks(
    *,
    critical_operation_pause_id: str | None = CRITICAL_OPERATION_PAUSE_ID,
    critical_operation_pause_duration: float = CRITICAL_OPERATION_PAUSE_DURATION,
) -> SimulationHooks:
    kairos_hooks = build_kairos_validation_hooks()

    def process_time(machine, batch, route_step, operation, rng):
        sampled_duration = default_process_time_hook(machine, batch, route_step, operation, rng)
        if operation.operation_id == critical_operation_pause_id:
            return sampled_duration + critical_operation_pause_duration
        return sampled_duration

    return SimulationHooks(
        setup_time=kairos_hooks.setup_time,
        process_time=process_time,
        setup_before_availability=kairos_hooks.setup_before_availability,
    )


def load_or_solve_fixed_kairos_schedule(
    *,
    time_limit_seconds: int,
    logging_enabled: bool,
    ortools_logging: bool,
    workers: int | None,
    relative_gap_limit: float | None,
    absolute_gap_limit: float | None,
    refresh_kairos: bool,
):
    if FIXED_KAIROS_SOLUTION_PATH.exists() and not refresh_kairos:
        with FIXED_KAIROS_SOLUTION_PATH.open("rb") as cache_file:
            cached = pickle.load(cache_file)
        print(f"[*] Sabit Kairos plani yuklendi: {FIXED_KAIROS_SOLUTION_PATH}")
        return cached["problem"], cached["solution"]

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

    FIXED_KAIROS_SOLUTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FIXED_KAIROS_SOLUTION_PATH.open("wb") as cache_file:
        pickle.dump({"problem": problem, "solution": solution}, cache_file)
    print(f"[*] Kairos plani bir kere uretildi ve sabitlendi: {FIXED_KAIROS_SOLUTION_PATH}")
    return problem, solution


def shift_bundle_start_time(base_bundle, start_hour_offset: float):
    if start_hour_offset <= 0:
        return base_bundle

    shifted_machines = [
        replace(
            machine,
            calendar=replace(
                machine.calendar,
                working_windows=tuple(
                    replace(
                        window,
                        start=window.start + start_hour_offset,
                        end=window.end + start_hour_offset,
                    )
                    for window in machine.calendar.working_windows
                ),
            ),
        )
        for machine in base_bundle.machines.values()
    ]

    shifted_batches = [
        replace(batch, release_time=batch.release_time + start_hour_offset)
        for batch in base_bundle.batches.values()
    ]

    shifted_operations = tuple(
        replace(
            operation,
            planned_start=operation.planned_start + start_hour_offset,
            planned_end=operation.planned_end + start_hour_offset,
        )
        for operation in base_bundle.schedule_operations
    )

    return build_schedule_bundle(
        week_horizon=base_bundle.week_horizon + start_hour_offset,
        machines=shifted_machines,
        batches=shifted_batches,
        schedule_operations=shifted_operations,
        basket_rules=base_bundle.basket_rules.values(),
        travel_matrix=base_bundle.travel_matrix,
        metadata={
            **base_bundle.metadata,
            "start_hour_offset": start_hour_offset,
        },
    )


def insert_production_pause(base_bundle, pause_duration: float = PRODUCTION_PAUSE_DURATION):
    if pause_duration <= 0:
        return base_bundle

    if not base_bundle.schedule_operations:
        return base_bundle

    first_operation = min(
        base_bundle.schedule_operations,
        key=lambda operation: (operation.planned_start, operation.planned_end, operation.operation_id),
    )
    pause_start = first_operation.planned_end
    pause_end = pause_start + pause_duration

    paused_machines = []
    for machine in base_bundle.machines.values():
        paused_machines.append(
            replace(
                machine,
                calendar=Calendar(
                    calendar_id=f"{machine.calendar.calendar_id}_production_pause",
                    working_windows=_split_windows_for_pause(
                        machine.calendar.working_windows,
                        pause_start=pause_start,
                        pause_end=pause_end,
                    ),
                ),
            )
        )

    return build_schedule_bundle(
        week_horizon=base_bundle.week_horizon,
        machines=paused_machines,
        batches=base_bundle.batches.values(),
        schedule_operations=base_bundle.schedule_operations,
        basket_rules=base_bundle.basket_rules.values(),
        travel_matrix=base_bundle.travel_matrix,
        metadata={
            **base_bundle.metadata,
            "production_pause_start": pause_start,
            "production_pause_end": pause_end,
            "production_pause_duration": pause_duration,
        },
    )


def insert_assembly_pause(base_bundle, pause_duration: float = ASSEMBLY_PAUSE_DURATION):
    if pause_duration <= 0:
        return base_bundle

    assembly_operations = [
        operation
        for operation in base_bundle.schedule_operations
        if _machine_group(operation.machine_id) == "ASSEMBLY"
    ]
    if not assembly_operations:
        return base_bundle

    first_assembly_operation = min(
        assembly_operations,
        key=lambda operation: (operation.planned_start, operation.planned_end, operation.operation_id),
    )
    pause_start = first_assembly_operation.planned_end
    pause_end = pause_start + pause_duration

    paused_machines = []
    for machine in base_bundle.machines.values():
        if _machine_group(machine.machine_id) != "ASSEMBLY":
            paused_machines.append(machine)
            continue

        paused_machines.append(
            replace(
                machine,
                calendar=Calendar(
                    calendar_id=f"{machine.calendar.calendar_id}_assembly_pause",
                    working_windows=_split_windows_for_pause(
                        machine.calendar.working_windows,
                        pause_start=pause_start,
                        pause_end=pause_end,
                    ),
                ),
            )
        )

    return build_schedule_bundle(
        week_horizon=base_bundle.week_horizon,
        machines=paused_machines,
        batches=base_bundle.batches.values(),
        schedule_operations=base_bundle.schedule_operations,
        basket_rules=base_bundle.basket_rules.values(),
        travel_matrix=base_bundle.travel_matrix,
        metadata={
            **base_bundle.metadata,
            "assembly_pause_start": pause_start,
            "assembly_pause_end": pause_end,
            "assembly_pause_duration": pause_duration,
        },
    )


def _split_windows_for_pause(working_windows, *, pause_start: float, pause_end: float):
    split_windows = []
    for window in working_windows:
        if pause_end <= window.start or pause_start >= window.end:
            split_windows.append(window)
            continue
        if window.start < pause_start:
            split_windows.append(TimeWindow(start=window.start, end=pause_start))
        if pause_end < window.end:
            split_windows.append(TimeWindow(start=pause_end, end=window.end))
    return tuple(split_windows)


def extend_bundle_horizon(base_bundle, horizon: float):
    if horizon <= base_bundle.week_horizon:
        return base_bundle

    extended_machines = []
    for machine in base_bundle.machines.values():
        working_windows = machine.calendar.working_windows
        last_window = working_windows[-1]
        extended_windows = (
            *working_windows[:-1],
            TimeWindow(start=last_window.start, end=max(last_window.end, horizon)),
        )
        extended_machines.append(
            replace(
                machine,
                calendar=Calendar(
                    calendar_id=f"{machine.calendar.calendar_id}_extended",
                    working_windows=extended_windows,
                ),
            )
        )

    return build_schedule_bundle(
        week_horizon=horizon,
        machines=extended_machines,
        batches=base_bundle.batches.values(),
        schedule_operations=base_bundle.schedule_operations,
        basket_rules=base_bundle.basket_rules.values(),
        travel_matrix=base_bundle.travel_matrix,
        metadata={
            **base_bundle.metadata,
            "completion_horizon": horizon,
        },
    )


def run_until_all_operations_complete(
    base_bundle,
    *,
    seed: int,
    hooks: SimulationHooks,
    trace: bool,
    initial_state: InitialSimulationState,
):
    planned_end = max(operation.planned_end for operation in base_bundle.schedule_operations)
    horizon = max(base_bundle.week_horizon, planned_end + COMPLETION_HORIZON_PADDING)

    for attempt in range(1, MAX_COMPLETION_HORIZON_ATTEMPTS + 1):
        execution_bundle = extend_bundle_horizon(base_bundle, horizon)
        result = run_week(
            execution_bundle,
            seed=seed,
            hooks=hooks,
            trace=trace,
            initial_state=initial_state,
        )
        unfinished_operations = [operation for operation in result.operations if operation.actual_end is None]
        if not unfinished_operations:
            return execution_bundle, result, attempt

        latest_completed_end = max(
            (operation.actual_end for operation in result.operations if operation.actual_end is not None),
            default=planned_end,
        )
        horizon = max(horizon * 1.5, latest_completed_end + COMPLETION_HORIZON_PADDING)

    unfinished_count = len([operation for operation in result.operations if operation.actual_end is None])
    raise RuntimeError(
        f"Simulation still has {unfinished_count} unfinished operations after "
        f"{MAX_COMPLETION_HORIZON_ATTEMPTS} horizon extensions."
    )


def build_demo_non_empty_initial_state(bundle, start_hour_offset: float) -> InitialSimulationState:
    root_operations = []
    for operation in sorted(
        bundle.schedule_operations,
        key=lambda item: (item.planned_start, item.machine_sequence, item.operation_id),
    ):
        batch = bundle.batches[operation.batch_id]
        step = next(step for step in batch.route if step.step_id == operation.step_id)
        if not step.predecessor_step_ids:
            root_operations.append(operation)

    operation_states = {}
    machine_states = {}
    seeded_machine_ids: set[str] = set()

    for operation in root_operations:
        if operation.machine_id in seeded_machine_ids:
            continue
        duration = max(1.0, operation.planned_end - operation.planned_start)
        elapsed = min(duration * 0.45, max(0.5, duration - 0.5))
        remaining = max(0.5, duration - elapsed)
        actual_start = start_hour_offset - elapsed

        operation_states[operation.operation_id] = InitialOperationState(
            operation_id=operation.operation_id,
            status="in_process",
            available_time=actual_start,
            actual_start=actual_start,
            sampled_process_time=duration,
            remaining_process_time=remaining,
        )
        machine_states[operation.machine_id] = InitialMachineState(machine_id=operation.machine_id)
        seeded_machine_ids.add(operation.machine_id)

        if len(seeded_machine_ids) >= 6:
            break

    return InitialSimulationState(
        start_time=start_hour_offset,
        operations=operation_states,
        machines=machine_states,
    )


def _build_failure_profile(machine_id: str):
    machine_group = _machine_group(machine_id)
    config = FAILURE_CONFIG_BY_MACHINE_GROUP.get(machine_group)
    if config is None:
        return None
    mean_uptime, mean_repair = config
    return build_failure_profile(
        profile_id=f"{machine_group.lower()}_stochastic_failures",
        uptime_distribution=build_distribution("exponential", mean=mean_uptime),
        repair_distribution=build_distribution(
            "triangular",
            low=max(1.0, mean_repair * 0.6),
            mode=mean_repair,
            high=mean_repair * 1.6,
        ),
    )


def _build_process_distribution(family_id: str, task_name: str, base_duration: float):
    low_factor, high_factor = _variability_factors(family_id=family_id, task_name=task_name)
    return build_distribution(
        "triangular",
        low=base_duration * low_factor,
        mode=base_duration,
        high=base_duration * high_factor,
    )


def _variability_factors(family_id: str, task_name: str) -> tuple[float, float]:
    family_adjustment = {
        "Bullet": (0.93, 1.14),
        "Wheel": (0.88, 1.24),
        "Slider": (0.91, 1.18),
        "Hinge": (0.92, 1.16),
    }.get(family_id, (0.92, 1.18))

    stage_adjustment = {
        "Assembly": (family_adjustment[0] - 0.05, family_adjustment[1] + 0.10),
        "Packaging": (family_adjustment[0] - 0.01, family_adjustment[1] - 0.03),
        "Shipping": (family_adjustment[0], family_adjustment[1] - 0.02),
        "Boxing": (family_adjustment[0], family_adjustment[1] - 0.02),
        "Welding": (family_adjustment[0] - 0.02, family_adjustment[1] + 0.04),
        "Wheel CNC": (family_adjustment[0] - 0.04, family_adjustment[1] + 0.06),
        "Bear Fasten": (family_adjustment[0] - 0.03, family_adjustment[1] + 0.05),
    }
    return stage_adjustment.get(task_name, family_adjustment)


def _build_layout_travel_matrix(base_bundle):
    machine_ids = sorted(base_bundle.machines)
    durations: dict[tuple[str, str], float] = {}
    for origin in machine_ids:
        for destination in machine_ids:
            if origin == destination:
                continue
            durations[(origin, destination)] = _travel_duration(origin, destination)
    return build_travel_matrix(durations)


def _travel_duration(origin_machine_id: str, destination_machine_id: str) -> float:
    origin_position = _machine_position(origin_machine_id)
    destination_position = _machine_position(destination_machine_id)
    base_distance = hypot(destination_position[0] - origin_position[0], destination_position[1] - origin_position[1])
    return round(0.5 + base_distance * 1.35, 2)


def _machine_position(machine_id: str) -> tuple[float, float]:
    machine_group = _machine_group(machine_id)
    base_x, base_y = LAYOUT_BY_MACHINE_GROUP[machine_group]
    machine_index = _machine_index(machine_id)
    return base_x, base_y + (machine_index - 1) * 0.35


def _machine_group(machine_id: str) -> str:
    return machine_id.split("-", 1)[0]


def _machine_index(machine_id: str) -> int:
    suffix = machine_id.split("-", 1)[1]
    return int(suffix)


def _print_stochastic_report(problem, solution, bundle, result, seed: int) -> None:
    completed_operations = [operation for operation in result.operations if operation.actual_end is not None]
    unfinished_operations = [operation for operation in result.operations if operation.actual_end is None]
    completed_batches = [batch for batch in result.batch_summaries if batch.completed]
    operation_deltas = []
    for operation in completed_operations:
        end_delta = operation.actual_end - operation.planned_end
        start_delta = operation.actual_start - operation.planned_start if operation.actual_start is not None else None
        operation_deltas.append((operation.operation_id, operation.machine_id, start_delta, end_delta))

    late_finishes = [delta for delta in operation_deltas if delta[3] is not None and delta[3] > 1e-9]
    early_starts = [delta for delta in operation_deltas if delta[2] is not None and delta[2] < -1e-9]
    worst_finish_deltas = sorted(operation_deltas, key=lambda item: item[3] if item[3] is not None else float("-inf"), reverse=True)

    print("Problem:", problem.name)
    print("Kairos status:", solution.status)
    print("Seed:", seed)
    print("Planned makespan:", max(operation.planned_end for operation in bundle.schedule_operations))
    actual_end_times = [operation.actual_end for operation in completed_operations if operation.actual_end is not None]
    print("Actual completed makespan:", max(actual_end_times) if actual_end_times else None)
    print("Completed operations:", len(completed_operations))
    print("Unfinished operations:", len(unfinished_operations))
    print("Completed batches:", len(completed_batches))
    print("Leftover batches:", len(result.leftover_batches))
    print("Early starts:", len(early_starts))
    print("Late finishes:", len(late_finishes))

    if operation_deltas:
        average_finish_delta = sum(delta[3] for delta in operation_deltas if delta[3] is not None) / len(operation_deltas)
        print("Average finish delta:", round(average_finish_delta, 2))

    print("Worst finish deltas:")
    for operation_id, machine_id, start_delta, end_delta in worst_finish_deltas[:12]:
        print(
            operation_id,
            machine_id,
            "start_delta=",
            round(start_delta, 2) if start_delta is not None else None,
            "end_delta=",
            round(end_delta, 2) if end_delta is not None else None,
        )


def _write_comparison_page(
    comparison_html_path: Path,
    kairos_html_path: Path,
    sim_html_path: Path,
    *,
    problem_name: str,
    seed: int,
    stochastic_result,
) -> None:
    completed_batches = len([batch for batch in stochastic_result.batch_summaries if batch.completed])
    comparison_html_path.write_text(
        "\n".join(
            [
                "<!DOCTYPE html>",
                "<html lang=\"en\">",
                "<head>",
                "  <meta charset=\"utf-8\">",
                f"  <title>{problem_name} - Stochastic Simulation Comparison</title>",
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
                f"  <div class=\"summary\"><h1>{problem_name} - Stochastic Simulation</h1>",
                f"  <p>Seed: {seed} | Completed batches: {completed_batches} | Leftover batches: {len(stochastic_result.leftover_batches)}</p>",
                "  <div class=\"links\">",
                f"    <a href=\"{kairos_html_path.name}\">Open Kairos baseline</a>",
                f"    <a href=\"{sim_html_path.name}\">Open stochastic simulation</a>",
                "  </div></div>",
                "  <h2>Kairos Baseline Schedule</h2>",
                f"  <iframe src=\"{kairos_html_path.name}\"></iframe>",
                "  <h2>Stochastic Simulation Schedule</h2>",
                f"  <iframe src=\"{sim_html_path.name}\"></iframe>",
                "</body>",
                "</html>",
            ]
        ),
        encoding="utf-8",
    )


def _build_operation_validation_rows(bundle, result):
    schedule_by_operation = {
        operation.operation_id: operation for operation in bundle.schedule_operations
    }
    rows = []
    for operation in result.operations:
        definition = schedule_by_operation[operation.operation_id]
        start_delta = (
            operation.actual_start - operation.planned_start
            if operation.actual_start is not None
            else None
        )
        end_delta = (
            operation.actual_end - operation.planned_end
            if operation.actual_end is not None
            else None
        )
        rows.append(
            {
                "Operation ID": operation.operation_id,
                "Batch ID": operation.batch_id,
                "Step ID": operation.step_id,
                "Machine ID": operation.machine_id,
                "Planned Start": round(operation.planned_start, 2),
                "Actual Start": round(operation.actual_start, 2) if operation.actual_start is not None else None,
                "Start Delta": round(start_delta, 2) if start_delta is not None else None,
                "Planned End": round(operation.planned_end, 2),
                "Actual End": round(operation.actual_end, 2) if operation.actual_end is not None else None,
                "End Delta": round(end_delta, 2) if end_delta is not None else None,
                "Status": operation.status,
                "Setup Start": round(operation.setup_started_at, 2) if operation.setup_started_at is not None else None,
                "Release Time": round(operation.release_time, 2) if operation.release_time is not None else None,
                "Downstream Available": round(operation.downstream_available_time, 2)
                if operation.downstream_available_time is not None
                else None,
                "Sampled Setup Time": round(operation.sampled_setup_time, 2),
                "Sampled Process Time": round(operation.sampled_process_time, 2),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["End Delta"] if row["End Delta"] is not None else float("-inf")
        ),
        reverse=True,
    )


def _build_kairos_schedule_rows(problem, solution):
    task_lookup = {
        str(task.id): task
        for task in problem.tasks
    }
    rows = []
    for scheduled_task in sorted(
        solution.schedule,
        key=lambda task: (float(task.start_time), str(task.machine_id), str(task.task_id)),
    ):
        task_id = str(scheduled_task.task_id)
        task = task_lookup.get(task_id)
        rows.append(
            {
                "Task ID": task_id,
                "Task Name": getattr(task, "name", None),
                "Job ID": None if task is None or task.job is None else str(task.job.id),
                "Machine ID": str(scheduled_task.machine_id),
                "Kairos Start": round(float(scheduled_task.start_time), 2),
                "Kairos End": round(float(scheduled_task.end_time), 2),
                "Kairos Duration": round(float(scheduled_task.duration), 2),
                "Release Time": round(float(getattr(task, "release_time", 0.0)), 2) if task is not None else None,
                "Task Type": str(task.get_effective_task_type()) if task is not None else None,
                "Setup Time": round(float(getattr(task, "setup_time", 0.0)), 2) if task is not None else None,
            }
        )
    return rows


def _build_simulation_operation_rows(result):
    rows = []
    for operation in sorted(
        result.operations,
        key=lambda item: (
            item.actual_start if item.actual_start is not None else float("inf"),
            item.machine_id,
            item.operation_id,
        ),
    ):
        start_delta = (
            operation.actual_start - operation.planned_start
            if operation.actual_start is not None
            else None
        )
        end_delta = (
            operation.actual_end - operation.planned_end
            if operation.actual_end is not None
            else None
        )
        rows.append(
            {
                "Operation ID": operation.operation_id,
                "Batch ID": operation.batch_id,
                "Step ID": operation.step_id,
                "Machine ID": operation.machine_id,
                "Planned Start": round(operation.planned_start, 2),
                "Planned End": round(operation.planned_end, 2),
                "Setup Started At": round(operation.setup_started_at, 2) if operation.setup_started_at is not None else None,
                "Actual Start": round(operation.actual_start, 2) if operation.actual_start is not None else None,
                "Actual End": round(operation.actual_end, 2) if operation.actual_end is not None else None,
                "Start Delta": round(start_delta, 2) if start_delta is not None else None,
                "End Delta": round(end_delta, 2) if end_delta is not None else None,
                "Release Time": round(operation.release_time, 2) if operation.release_time is not None else None,
                "Downstream Available": round(operation.downstream_available_time, 2)
                if operation.downstream_available_time is not None
                else None,
                "Sampled Setup Time": round(operation.sampled_setup_time, 2),
                "Sampled Process Time": round(operation.sampled_process_time, 2),
                "Status": operation.status,
            }
        )
    return rows


def _build_simulation_event_rows(result):
    import json

    rows = []
    for event in result.events:
        rows.append(
            {
                "Time": round(event.time, 2),
                "Event Type": event.event_type,
                "Machine ID": event.machine_id,
                "Batch ID": event.batch_id,
                "Operation ID": event.operation_id,
                "Details": json.dumps(event.details, ensure_ascii=False, sort_keys=True, default=str),
            }
        )
    return rows


def _build_product_completion_rows(bundle, result):
    batches_by_id = bundle.batches
    kairos_by_batch: dict[str, dict[str, float]] = {}
    for operation in bundle.schedule_operations:
        summary = kairos_by_batch.setdefault(
            operation.batch_id,
            {
                "planned_start": operation.planned_start,
                "planned_end": operation.planned_end,
                "operation_count": 0,
            },
        )
        summary["planned_start"] = min(summary["planned_start"], operation.planned_start)
        summary["planned_end"] = max(summary["planned_end"], operation.planned_end)
        summary["operation_count"] += 1

    simulation_by_batch: dict[str, dict[str, float | int | bool | None]] = {}
    for operation in result.operations:
        summary = simulation_by_batch.setdefault(
            operation.batch_id,
            {
                "actual_start": operation.actual_start,
                "actual_end": operation.actual_end,
                "completed_operation_count": 0,
                "unfinished_operation_count": 0,
            },
        )
        if operation.actual_start is not None:
            current_start = summary["actual_start"]
            summary["actual_start"] = (
                operation.actual_start
                if current_start is None
                else min(float(current_start), operation.actual_start)
            )
        if operation.actual_end is not None:
            current_end = summary["actual_end"]
            summary["actual_end"] = (
                operation.actual_end
                if current_end is None
                else max(float(current_end), operation.actual_end)
            )
            summary["completed_operation_count"] = int(summary["completed_operation_count"]) + 1
        else:
            summary["unfinished_operation_count"] = int(summary["unfinished_operation_count"]) + 1

    rows = []
    for batch_id in sorted(kairos_by_batch):
        batch = batches_by_id[batch_id]
        kairos = kairos_by_batch[batch_id]
        simulation = simulation_by_batch.get(batch_id, {})
        planned_start = float(kairos["planned_start"])
        planned_end = float(kairos["planned_end"])
        actual_start = simulation.get("actual_start")
        actual_end = simulation.get("actual_end")
        planned_elapsed = planned_end - planned_start
        actual_elapsed = (
            float(actual_end) - float(actual_start)
            if actual_start is not None and actual_end is not None
            else None
        )
        completion_delta = (
            float(actual_end) - planned_end
            if actual_end is not None
            else None
        )
        rows.append(
            {
                "Batch ID": batch_id,
                "Product ID": batch.product_id,
                "Family ID": batch.family_id,
                "Quantity": batch.quantity,
                "Kairos Start": round(planned_start, 2),
                "Kairos End": round(planned_end, 2),
                "Kairos Elapsed": round(planned_elapsed, 2),
                "Simulation Start": round(float(actual_start), 2) if actual_start is not None else None,
                "Simulation End": round(float(actual_end), 2) if actual_end is not None else None,
                "Simulation Elapsed": round(actual_elapsed, 2) if actual_elapsed is not None else None,
                "Completion Delta": round(completion_delta, 2) if completion_delta is not None else None,
                "Operation Count": int(kairos["operation_count"]),
                "Completed Operations": simulation.get("completed_operation_count", 0),
                "Unfinished Operations": simulation.get("unfinished_operation_count", 0),
            }
        )
    return rows


def _build_batch_summary_rows(result):
    rows = []
    for batch in result.batch_summaries:
        rows.append(
            {
                "Batch ID": batch.batch_id,
                "Product ID": batch.product_id,
                "Quantity": batch.quantity,
                "Completed": batch.completed,
                "Current Stage": batch.current_stage,
                "Pending Operation ID": batch.pending_operation_id,
                "Current Machine ID": batch.current_machine_id,
                "Finished At": round(batch.finished_at, 2) if batch.finished_at is not None else None,
            }
        )
    return rows


def _build_machine_summary_rows(result):
    rows = []
    for machine in result.machine_summaries:
        rows.append(
            {
                "Machine ID": machine.machine_id,
                "Completed Operations": machine.completed_operations,
                "Productive Time": round(machine.productive_time, 2),
                "Setup Time": round(machine.setup_time, 2),
                "Downtime Time": round(machine.downtime_time, 2),
                "Calendar Pause Time": round(machine.calendar_pause_time, 2),
                "Waiting for Batch": round(machine.waiting_for_batch_time, 2),
                "Waiting for Basket": round(machine.waiting_for_basket_time, 2),
                "Waiting for Schedule": round(machine.waiting_for_schedule_time, 2),
                "Idle Time": round(machine.idle_time, 2),
                "Blocked Time": round(machine.blocked_time, 2),
            }
        )
    return rows


def _write_validation_excel_report(
    excel_path: Path,
    *,
    problem,
    solution,
    problem_name: str,
    seed: int,
    start_hour_offset: float,
    num_replications: int,
    planned_makespan: float,
    mean_makespan: float,
    std_makespan: float,
    ci_lower: float,
    ci_upper: float,
    sapma_yuzdesi: float,
    replication_rows,
    bundle,
    stochastic_result,
) -> Path:
    import pandas as pd

    summary_rows = [
        {"Metrik": "Problem", "Değer": problem_name},
        {"Metrik": "Seed", "Değer": seed},
        {"Metrik": "Başlangıç Ofseti [saat]", "Değer": round(start_hour_offset, 2)},
        {"Metrik": "Kritik Duraksatılan İş", "Değer": CRITICAL_OPERATION_PAUSE_ID},
        {"Metrik": "Kritik İş Duraksama Süresi [saat]", "Değer": CRITICAL_OPERATION_PAUSE_DURATION},
        {"Metrik": "Assembly Pause Start [saat]", "Değer": round(bundle.metadata.get("assembly_pause_start", 0.0), 2)},
        {"Metrik": "Assembly Pause End [saat]", "Değer": round(bundle.metadata.get("assembly_pause_end", 0.0), 2)},
        {"Metrik": "Assembly Pause Duration [saat]", "Değer": round(bundle.metadata.get("assembly_pause_duration", 0.0), 2)},
        {"Metrik": "Toplam Replikasyon Sayısı", "Değer": num_replications},
        {"Metrik": "Deterministik Plan (Kairos) [saat]", "Değer": round(planned_makespan, 2)},
        {"Metrik": "Simülasyon Ortalama Bitiş [saat]", "Değer": round(mean_makespan, 2)},
        {"Metrik": "Standart Sapma [saat]", "Değer": round(std_makespan, 2)},
        {"Metrik": "%95 Güven Aralığı Alt Sınır [saat]", "Değer": round(ci_lower, 2)},
        {"Metrik": "%95 Güven Aralığı Üst Sınır [saat]", "Değer": round(ci_upper, 2)},
        {"Metrik": "Planlanan Süreden Sapma [%]", "Değer": round(sapma_yuzdesi, 2)},
        {
            "Metrik": "Tamamlanan Batch Sayısı (son koşu)",
            "Değer": len([batch for batch in stochastic_result.batch_summaries if batch.completed]),
        },
        {"Metrik": "Leftover Batch Sayısı (son koşu)", "Değer": len(stochastic_result.leftover_batches)},
    ]

    df_summary = pd.DataFrame(summary_rows)
    df_kairos_schedule = pd.DataFrame(_build_kairos_schedule_rows(problem, solution))
    df_replications = pd.DataFrame(replication_rows)
    df_operations = pd.DataFrame(_build_operation_validation_rows(bundle, stochastic_result))
    df_simulation_operations = pd.DataFrame(_build_simulation_operation_rows(stochastic_result))
    df_simulation_events = pd.DataFrame(_build_simulation_event_rows(stochastic_result))
    df_product_completion = pd.DataFrame(_build_product_completion_rows(bundle, stochastic_result))
    df_batches = pd.DataFrame(_build_batch_summary_rows(stochastic_result))
    df_machines = pd.DataFrame(_build_machine_summary_rows(stochastic_result))

    def write_workbook(path: Path) -> None:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df_summary.to_excel(writer, sheet_name="Ozet", index=False)
            df_kairos_schedule.to_excel(writer, sheet_name="Kairos Schedule", index=False)
            df_replications.to_excel(writer, sheet_name="Replikasyonlar", index=False)
            df_operations.to_excel(writer, sheet_name="Operasyon Sapmalari", index=False)
            df_product_completion.to_excel(writer, sheet_name="Urun Tamamlanma", index=False)
            df_simulation_operations.to_excel(writer, sheet_name="Simulasyon Operasyonlari", index=False)
            df_simulation_events.to_excel(writer, sheet_name="Simulasyon Eventleri", index=False)
            df_batches.to_excel(writer, sheet_name="Batch Ozeti", index=False)
            df_machines.to_excel(writer, sheet_name="Makine Ozeti", index=False)

    try:
        write_workbook(excel_path)
        return excel_path
    except PermissionError:
        fallback_path = excel_path.with_name(f"{excel_path.stem}_yeni{excel_path.suffix}")
        write_workbook(fallback_path)
        return fallback_path

def main(
    *,
    seed: int = 17,
    start_hour_offset: float = DEFAULT_START_HOUR_OFFSET,
    time_limit_seconds: int = DEMO_SOLVE_TIME_LIMIT_SECONDS,
    logging_enabled: bool = DEMO_SOLVER_LOGGING_ENABLED,
    ortools_logging: bool = DEMO_ORTOOLS_LOGGING_ENABLED,
    workers: int | None = DEMO_SOLVER_WORKERS,
    relative_gap_limit: float | None = DEMO_RELATIVE_GAP_LIMIT,
    absolute_gap_limit: float | None = DEMO_ABSOLUTE_GAP_LIMIT,
    refresh_kairos: bool = False,
) -> None:
    problem, solution = load_or_solve_fixed_kairos_schedule(
        time_limit_seconds=time_limit_seconds,
        logging_enabled=logging_enabled,
        ortools_logging=ortools_logging,
        workers=workers,
        relative_gap_limit=relative_gap_limit,
        absolute_gap_limit=absolute_gap_limit,
        refresh_kairos=refresh_kairos,
    )

    conversion = build_schedule_bundle_from_kairos(problem, solution)
    stochastic_bundle = build_stochastic_execution_bundle(conversion.schedule_bundle)
    stochastic_bundle = shift_bundle_start_time(stochastic_bundle, start_hour_offset)
    report_bundle = stochastic_bundle
    stochastic_hooks = build_stochastic_execution_hooks()
    initial_state = InitialSimulationState(start_time=start_hour_offset)
    import numpy as np

    num_replications = 100
    actual_makespans = []
    replication_rows = []
    raw_planned_makespan = max(operation.planned_end for operation in stochastic_bundle.schedule_operations)
    planned_makespan = raw_planned_makespan - start_hour_offset

    print(
        f"\n[*] 100 Replikasyon calistiriliyor "
        f"(Baslangic: {start_hour_offset:.2f}. saat, bos initial state, "
        f"kritik is {CRITICAL_OPERATION_PAUSE_ID} +{CRITICAL_OPERATION_PAUSE_DURATION:.2f} saat duraksama, "
        f"Net Hedef: {planned_makespan:.2f})..."
    )

    for i in range(num_replications):
        current_bundle, current_result, horizon_attempts = run_until_all_operations_complete(
            stochastic_bundle,
            seed=i,
            hooks=stochastic_hooks,
            trace=False,
            initial_state=initial_state,
        )
        report_bundle = current_bundle

        completed_ops = [op for op in current_result.operations if op.actual_end is not None]
        net_makespan = None
        if completed_ops:
            net_makespan = max(op.actual_end for op in completed_ops) - start_hour_offset
            actual_makespans.append(net_makespan)

        replication_rows.append(
            {
                "Replication": i + 1,
                "Seed": i,
                "Net Makespan [saat]": round(net_makespan, 2) if net_makespan is not None else None,
                "Completed Operations": len(completed_ops),
                "Unfinished Operations": len([op for op in current_result.operations if op.actual_end is None]),
                "Completed Batches": len([batch for batch in current_result.batch_summaries if batch.completed]),
                "Leftover Batches": len(current_result.leftover_batches),
                "Horizon Attempts": horizon_attempts,
                "Simulation Horizon [saat]": round(current_bundle.week_horizon, 2),
            }
        )
             
        if i == num_replications - 1:
            stochastic_result = current_result
            report_bundle = current_bundle

    # --- İSTATİSTİKSEL HESAPLAMALAR ---
    mean_makespan = np.mean(actual_makespans)
    std_makespan = np.std(actual_makespans, ddof=1)
    
    # %95 Güven Aralığı Hesaplaması
    ci_lower = mean_makespan - 1.96 * (std_makespan / np.sqrt(num_replications))
    ci_upper = mean_makespan + 1.96 * (std_makespan / np.sqrt(num_replications))
    sapma_yuzdesi = ((mean_makespan - planned_makespan) / planned_makespan) * 100

    print("\n" + "="*50)
    print("      SİMÜLASYON DOĞRULAMA (VALIDATION) RAPORU")
    print("="*50)
    print(f"Toplam Replikasyon Sayısı : {num_replications}")
    print(f"Deterministik Plan (Kairos) : {planned_makespan:.2f} saat")
    print(f"Simülasyon Ortalama Bitiş : {mean_makespan:.2f} saat")
    print(f"Standart Sapma : {std_makespan:.2f} saat")
    print(f"%95 Güven Aralığı (CI) : [{ci_lower:.2f} - {ci_upper:.2f}] saat")
    print(f"Planlanan Süreden Sapma : %{sapma_yuzdesi:.2f}")
    print("="*50 + "\n")
    # --- EXCEL'E AKTARMA KISMI BAŞLANGICI ---
    output_yolu = PROJECT_ROOT / "examples" / "output"
    output_yolu.mkdir(parents=True, exist_ok=True)
    excel_dosya_adi = output_yolu / "Stokastik_Dogrulama_Raporu.xlsx"

    written_excel_path = _write_validation_excel_report(
        excel_dosya_adi,
        problem=problem,
        solution=solution,
        problem_name=problem.name,
        seed=seed,
        start_hour_offset=start_hour_offset,
        num_replications=num_replications,
        planned_makespan=planned_makespan,
        mean_makespan=mean_makespan,
        std_makespan=std_makespan,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        sapma_yuzdesi=sapma_yuzdesi,
        replication_rows=replication_rows,
        bundle=report_bundle,
        stochastic_result=stochastic_result,
    )
    print(f"[*] SİMÜLASYON RAPORU EXCEL'E KAYDEDİLDİ: {written_excel_path}\n")
    # --- EXCEL'E AKTARMA KISMI BİTİŞİ ---
    machine_names = machine_names_for_problem(problem)

    output_dir = PROJECT_ROOT / "examples" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    kairos_html_path = output_dir / "large_kairos_stochastic_baseline.html"
    stochastic_html_path = output_dir / "large_sim_stochastic_execution.html"
    comparison_html_path = output_dir / "large_stochastic_comparison.html"

    KairosGanttVisualizer(color_by="job_family").save_html(
        solution,
        str(kairos_html_path),
        title=f"{problem.name} - Kairos Baseline",
        machine_names=machine_names,
    )
    SimulationGanttVisualizer(color_by="family_id").save_html(
        result=stochastic_result,
        schedule_bundle=report_bundle,
        file_path=str(stochastic_html_path),
        title=f"{problem.name} - Stochastic Simulation",
    )
    _write_comparison_page(
        comparison_html_path=comparison_html_path,
        kairos_html_path=kairos_html_path,
        sim_html_path=stochastic_html_path,
        problem_name=problem.name,
        seed=seed,
        stochastic_result=stochastic_result,
    )

    _print_stochastic_report(problem, solution, report_bundle, stochastic_result, seed)
    print("Kairos baseline HTML:", kairos_html_path)
    print("Stochastic simulation HTML:", stochastic_html_path)
    print("Comparison HTML:", comparison_html_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the large stochastic execution demo from a Kairos baseline.")
    parser.add_argument(
        "--seed",
        type=int,
        default=17,
        help="Random seed for the stochastic simulation.",
    )
    parser.add_argument(
        "--start-hour",
        type=float,
        default=DEFAULT_START_HOUR_OFFSET,
        help="Simulation start hour offset. Use 17 to start the timeline from hour 17.",
    )
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
    parser.add_argument(
        "--refresh-kairos",
        action="store_true",
        help="Ignore the fixed cached Kairos schedule and solve/cache a new one.",
    )
    args = parser.parse_args()
    main(
        seed=args.seed,
        start_hour_offset=args.start_hour,
        time_limit_seconds=args.time_limit,
        logging_enabled=not args.quiet_kairos,
        ortools_logging=not args.quiet_kairos,
        workers=args.workers,
        relative_gap_limit=args.relative_gap,
        absolute_gap_limit=args.absolute_gap,
        refresh_kairos=args.refresh_kairos,
    )

