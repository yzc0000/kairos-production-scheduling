from __future__ import annotations

from dataclasses import dataclass

from .engine import run_week
from .hooks import SimulationHooks
from .models import ScheduleBundle, SimulationResult


@dataclass(frozen=True, slots=True)
class OperationValidation:
    operation_id: str
    batch_id: str
    machine_id: str
    planned_start: float
    planned_end: float
    actual_start: float | None
    actual_end: float | None
    start_delta: float | None
    end_delta: float | None
    matches_exactly: bool


@dataclass(frozen=True, slots=True)
class DeterministicValidationReport:
    schedule_bundle: ScheduleBundle
    simulation_result: SimulationResult
    operation_validations: tuple[OperationValidation, ...]
    exact_match: bool
    planned_makespan: float
    actual_makespan: float | None
    makespan_delta: float | None


def validate_deterministic_execution(
    schedule_bundle: ScheduleBundle,
    seed: int = 0,
    hooks: SimulationHooks | None = None,
    trace: bool = False,
    tolerance: float = 1e-9,
) -> DeterministicValidationReport:
    simulation_result = run_week(schedule_bundle, seed=seed, hooks=hooks, trace=trace)
    simulated_by_operation_id = {
        operation.operation_id: operation for operation in simulation_result.operations
    }

    operation_validations = []
    for planned_operation in schedule_bundle.schedule_operations:
        simulated_operation = simulated_by_operation_id[planned_operation.operation_id]
        start_delta = None
        end_delta = None
        if simulated_operation.actual_start is not None:
            start_delta = simulated_operation.actual_start - planned_operation.planned_start
        if simulated_operation.actual_end is not None:
            end_delta = simulated_operation.actual_end - planned_operation.planned_end

        matches_exactly = (
            start_delta is not None
            and end_delta is not None
            and abs(start_delta) <= tolerance
            and abs(end_delta) <= tolerance
        )
        operation_validations.append(
            OperationValidation(
                operation_id=planned_operation.operation_id,
                batch_id=planned_operation.batch_id,
                machine_id=planned_operation.machine_id,
                planned_start=planned_operation.planned_start,
                planned_end=planned_operation.planned_end,
                actual_start=simulated_operation.actual_start,
                actual_end=simulated_operation.actual_end,
                start_delta=start_delta,
                end_delta=end_delta,
                matches_exactly=matches_exactly,
            )
        )

    planned_makespan = max((operation.planned_end for operation in schedule_bundle.schedule_operations), default=0.0)
    actual_end_times = [operation.actual_end for operation in simulation_result.operations if operation.actual_end is not None]
    actual_makespan = max(actual_end_times) if actual_end_times else None
    makespan_delta = None if actual_makespan is None else actual_makespan - planned_makespan

    return DeterministicValidationReport(
        schedule_bundle=schedule_bundle,
        simulation_result=simulation_result,
        operation_validations=tuple(operation_validations),
        exact_match=all(operation.matches_exactly for operation in operation_validations),
        planned_makespan=planned_makespan,
        actual_makespan=actual_makespan,
        makespan_delta=makespan_delta,
    )
