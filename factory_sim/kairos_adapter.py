from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .builders import (
    build_batch,
    build_basket_rule,
    build_calendar,
    build_distribution,
    build_machine,
    build_route_step,
    build_schedule_bundle,
    build_schedule_operation,
    build_time_window,
    build_travel_matrix,
)
from .hooks import SimulationHooks
from .validator import DeterministicValidationReport, validate_deterministic_execution

if TYPE_CHECKING:
    from .models import ScheduleBundle


@dataclass(frozen=True, slots=True)
class KairosConversionResult:
    schedule_bundle: "ScheduleBundle"
    hooks: SimulationHooks


def build_schedule_bundle_from_kairos(
    problem: Any,
    solution: Any,
    horizon_padding: float = 1.0,
) -> KairosConversionResult:
    if not getattr(solution, "is_success", False):
        raise ValueError(f"Kairos solution is not successful: {getattr(solution, 'status', 'UNKNOWN')}")

    scheduled_by_task_id = {
        _normalize_id(scheduled_task.task_id): scheduled_task
        for scheduled_task in solution.schedule
    }
    all_tasks = list(problem.tasks)
    missing = [_normalize_id(task.id) for task in all_tasks if _normalize_id(task.id) not in scheduled_by_task_id]
    if missing:
        raise ValueError(f"Kairos solution is missing scheduled tasks: {missing}")

    group_by_task_id = _group_tasks_into_batches(problem)
    tasks_by_group: dict[str, list[Any]] = defaultdict(list)
    for task in all_tasks:
        tasks_by_group[group_by_task_id[_normalize_id(task.id)]].append(task)

    machine_ids = sorted({_normalize_id(machine.id) for machine in problem.machines.values()})
    planned_makespan = max(float(scheduled_task.end_time) for scheduled_task in solution.schedule) if solution.schedule else 0.0
    horizon = planned_makespan + horizon_padding

    calendar = build_calendar("kairos_full_horizon", [build_time_window(0.0, max(horizon, 1.0))])
    machines = [
        build_machine(
            machine_id=_normalize_id(machine.id),
            calendar=calendar,
            fixed_setup_time=0.0,
            name=machine.name,
            metadata={"source": "kairos"},
        )
        for machine in problem.machines.values()
    ]

    batches = []
    schedule_operations = []
    basket_rules: dict[tuple[str, str], Any] = {}

    for group_id, tasks in sorted(tasks_by_group.items(), key=lambda item: item[0]):
        topological_levels = _compute_topological_levels(tasks)
        product_id = _derive_product_id(tasks, group_id)
        family_id = _derive_family_id(tasks)
        root_release_times = []
        route_steps = []

        for task in sorted(tasks, key=lambda item: (topological_levels[_normalize_id(item.id)], _normalize_id(item.id))):
            task_id = _normalize_id(task.id)
            scheduled_task = scheduled_by_task_id[task_id]
            predecessor_step_ids = tuple(_normalize_id(pred.id) for pred in task.predecessors if _normalize_id(pred.id) in topological_levels)
            if not predecessor_step_ids:
                root_release_times.append(float(getattr(task, "release_time", 0.0)))

            route_steps.append(
                build_route_step(
                    step_id=task_id,
                    sequence=topological_levels[task_id],
                    process_time_per_unit=build_distribution("deterministic", value=float(scheduled_task.duration)),
                    predecessor_step_ids=predecessor_step_ids,
                    name=task.name,
                    metadata={
                        "source": "kairos",
                        "task_name": task.name,
                        "setup_key": str(task.get_effective_task_type()),
                        "task_setup_time": float(task.setup_time),
                        "release_time": float(getattr(task, "release_time", 0.0)),
                    },
                )
            )

        batch = build_batch(
            batch_id=group_id,
            product_id=product_id,
            quantity=1.0,
            route=route_steps,
            family_id=family_id,
            release_time=min(root_release_times) if root_release_times else 0.0,
            metadata={"source": "kairos"},
        )
        batches.append(batch)

        for task in tasks:
            task_id = _normalize_id(task.id)
            scheduled_task = scheduled_by_task_id[task_id]
            machine_id = _normalize_id(scheduled_task.machine_id)
            basket_rules.setdefault((machine_id, product_id), build_basket_rule(machine_id, product_id, 1.0))
            schedule_operations.append(
                build_schedule_operation(
                    operation_id=task_id,
                    batch_id=group_id,
                    step_id=task_id,
                    machine_id=machine_id,
                    machine_sequence=0,
                    planned_start=float(scheduled_task.start_time),
                    planned_end=float(scheduled_task.end_time),
                    metadata={
                        "source": "kairos",
                        "task_name": task.name,
                        "job_id": None if task.job is None else _normalize_id(task.job.id),
                        "setup_key": str(task.get_effective_task_type()),
                        "task_setup_time": float(task.setup_time),
                        "release_time": float(getattr(task, "release_time", 0.0)),
                        "scheduled_duration": float(scheduled_task.duration),
                    },
                )
            )

    schedule_operations = _assign_machine_sequences(schedule_operations)
    travel_matrix = build_travel_matrix(
        {
            (origin, destination): 0.0
            for origin in machine_ids
            for destination in machine_ids
            if origin != destination
        }
    )

    schedule_bundle = build_schedule_bundle(
        week_horizon=max(horizon, 1.0),
        machines=machines,
        batches=batches,
        schedule_operations=schedule_operations,
        basket_rules=list(basket_rules.values()),
        travel_matrix=travel_matrix,
        metadata={"source": "kairos"},
    )
    return KairosConversionResult(
        schedule_bundle=schedule_bundle,
        hooks=build_kairos_validation_hooks(),
    )


def build_kairos_validation_hooks() -> SimulationHooks:
    return SimulationHooks(
        setup_time=_kairos_setup_time_hook,
        earliest_setup_start=_kairos_earliest_setup_start_hook,
        setup_before_availability=_kairos_setup_before_availability_hook,
    )


def validate_kairos_solution(
    problem: Any,
    solution: Any,
    seed: int = 0,
    trace: bool = False,
    tolerance: float = 1e-9,
    horizon_padding: float = 1.0,
) -> DeterministicValidationReport:
    conversion = build_schedule_bundle_from_kairos(
        problem=problem,
        solution=solution,
        horizon_padding=horizon_padding,
    )
    return validate_deterministic_execution(
        schedule_bundle=conversion.schedule_bundle,
        seed=seed,
        hooks=conversion.hooks,
        trace=trace,
        tolerance=tolerance,
    )


def _kairos_setup_time_hook(
    machine: Any,
    previous_operation: Any | None,
    previous_batch: Any | None,
    operation: Any,
    current_batch: Any,
) -> float:
    if previous_operation is None:
        return 0.0
    previous_key = previous_operation.metadata.get("setup_key")
    current_key = operation.metadata.get("setup_key")
    if previous_key == current_key:
        return 0.0
    return float(operation.metadata.get("task_setup_time", 0.0))


def _kairos_earliest_setup_start_hook(
    machine: Any,
    operation: Any,
    batch: Any,
    setup_time: float,
) -> float:
    return max(0.0, float(operation.planned_start) - setup_time)


def _kairos_setup_before_availability_hook(
    machine: Any,
    operation: Any,
    batch: Any,
) -> bool:
    return True


def _normalize_id(value: Any) -> str:
    return str(value)


def _group_tasks_into_batches(problem: Any) -> dict[str, str]:
    tasks = list(problem.tasks)
    normalized_ids = {_normalize_id(task.id): task for task in tasks}
    adjacency: dict[str, set[str]] = {task_id: set() for task_id in normalized_ids}

    for task in tasks:
        task_id = _normalize_id(task.id)
        for predecessor in task.predecessors:
            predecessor_id = _normalize_id(predecessor.id)
            if predecessor_id in adjacency:
                adjacency[task_id].add(predecessor_id)
                adjacency[predecessor_id].add(task_id)

    for job in problem.jobs:
        job_task_ids = [_normalize_id(task.id) for task in job.tasks if _normalize_id(task.id) in adjacency]
        if len(job_task_ids) <= 1:
            continue
        anchor = job_task_ids[0]
        for task_id in job_task_ids[1:]:
            adjacency[anchor].add(task_id)
            adjacency[task_id].add(anchor)

    task_to_group: dict[str, str] = {}
    visited: set[str] = set()
    component_index = 1
    for task_id in sorted(adjacency):
        if task_id in visited:
            continue
        stack = [task_id]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(sorted(adjacency[current] - visited))

        component_tasks = [normalized_ids[item] for item in component]
        component_job_ids = {
            _normalize_id(task.job.id)
            for task in component_tasks
            if getattr(task, "job", None) is not None
        }
        if len(component_job_ids) == 1:
            group_id = f"job::{next(iter(component_job_ids))}"
        else:
            group_id = f"component::{component_index}"
            component_index += 1

        for component_task_id in component:
            task_to_group[component_task_id] = group_id

    return task_to_group


def _compute_topological_levels(tasks: list[Any]) -> dict[str, int]:
    task_by_id = {_normalize_id(task.id): task for task in tasks}
    cache: dict[str, int] = {}

    def level(task_id: str) -> int:
        if task_id in cache:
            return cache[task_id]
        task = task_by_id[task_id]
        predecessor_ids = [_normalize_id(pred.id) for pred in task.predecessors if _normalize_id(pred.id) in task_by_id]
        if not predecessor_ids:
            cache[task_id] = 1
            return 1
        cache[task_id] = 1 + max(level(predecessor_id) for predecessor_id in predecessor_ids)
        return cache[task_id]

    return {task_id: level(task_id) for task_id in task_by_id}


def _derive_product_id(tasks: list[Any], fallback_group_id: str) -> str:
    job_names = {task.job.name for task in tasks if getattr(task, "job", None) is not None}
    if len(job_names) == 1:
        return next(iter(job_names))
    return fallback_group_id


def _derive_family_id(tasks: list[Any]) -> str | None:
    task_types = {
        str(task.job.task_type)
        for task in tasks
        if getattr(task, "job", None) is not None and getattr(task.job, "task_type", None) is not None
    }
    if len(task_types) == 1:
        return next(iter(task_types))
    return None


def _assign_machine_sequences(schedule_operations: list[Any]) -> list[Any]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for operation in schedule_operations:
        grouped[operation.machine_id].append(operation)

    sequenced_operations = []
    for machine_id, operations in grouped.items():
        ordered = sorted(
            operations,
            key=lambda operation: (
                operation.planned_start,
                operation.planned_end,
                operation.operation_id,
            ),
        )
        for sequence, operation in enumerate(ordered, start=1):
            sequenced_operations.append(
                build_schedule_operation(
                    operation_id=operation.operation_id,
                    batch_id=operation.batch_id,
                    step_id=operation.step_id,
                    machine_id=machine_id,
                    machine_sequence=sequence,
                    planned_start=operation.planned_start,
                    planned_end=operation.planned_end,
                    metadata=operation.metadata,
                )
            )

    return sorted(sequenced_operations, key=lambda operation: (operation.machine_id, operation.machine_sequence))
