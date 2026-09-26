from __future__ import annotations

from typing import Any, Iterable, Mapping

from .models import (
    BasketRule,
    Batch,
    Calendar,
    DistributionSpec,
    FailureProfile,
    Machine,
    RouteStep,
    ScheduleBundle,
    ScheduleOperation,
    TimeWindow,
    TravelMatrix,
)
from .validation import validate_schedule_bundle


def build_distribution(kind: str, **parameters: float) -> DistributionSpec:
    return DistributionSpec(kind=kind, parameters=parameters)


def build_time_window(start: float, end: float) -> TimeWindow:
    return TimeWindow(start=start, end=end)


def build_calendar(calendar_id: str, working_windows: Iterable[TimeWindow]) -> Calendar:
    return Calendar(calendar_id=calendar_id, working_windows=tuple(working_windows))


def build_failure_profile(
    profile_id: str,
    uptime_distribution: DistributionSpec | None = None,
    repair_distribution: DistributionSpec | None = None,
) -> FailureProfile:
    return FailureProfile(
        profile_id=profile_id,
        uptime_distribution=uptime_distribution,
        repair_distribution=repair_distribution,
    )


def build_machine(
    machine_id: str,
    calendar: Calendar,
    fixed_setup_time: float = 0.0,
    failure_profile: FailureProfile | None = None,
    name: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Machine:
    return Machine(
        machine_id=machine_id,
        calendar=calendar,
        fixed_setup_time=fixed_setup_time,
        failure_profile=failure_profile,
        name=name,
        metadata=metadata or {},
    )


def build_route_step(
    step_id: str,
    sequence: int,
    process_time_per_unit: DistributionSpec,
    predecessor_step_ids: Iterable[str] | None = None,
    name: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RouteStep:
    return RouteStep(
        step_id=step_id,
        sequence=sequence,
        process_time_per_unit=process_time_per_unit,
        predecessor_step_ids=None if predecessor_step_ids is None else tuple(predecessor_step_ids),
        name=name,
        metadata=metadata or {},
    )


def build_batch(
    batch_id: str,
    product_id: str,
    quantity: float,
    route: Iterable[RouteStep],
    family_id: str | None = None,
    release_time: float = 0.0,
    metadata: Mapping[str, Any] | None = None,
) -> Batch:
    return Batch(
        batch_id=batch_id,
        product_id=product_id,
        quantity=quantity,
        route=tuple(route),
        family_id=family_id,
        release_time=release_time,
        metadata=metadata or {},
    )


def build_basket_rule(machine_id: str, product_id: str, capacity_quantity: float) -> BasketRule:
    return BasketRule(machine_id=machine_id, product_id=product_id, capacity_quantity=capacity_quantity)


def build_schedule_operation(
    operation_id: str,
    batch_id: str,
    step_id: str,
    machine_id: str,
    machine_sequence: int,
    planned_start: float,
    planned_end: float,
    metadata: Mapping[str, Any] | None = None,
) -> ScheduleOperation:
    return ScheduleOperation(
        operation_id=operation_id,
        batch_id=batch_id,
        step_id=step_id,
        machine_id=machine_id,
        machine_sequence=machine_sequence,
        planned_start=planned_start,
        planned_end=planned_end,
        metadata=metadata or {},
    )


def build_travel_matrix(durations: Mapping[tuple[str, str], float]) -> TravelMatrix:
    return TravelMatrix(durations=durations)


def build_schedule_bundle(
    week_horizon: float,
    machines: Iterable[Machine],
    batches: Iterable[Batch],
    schedule_operations: Iterable[ScheduleOperation],
    basket_rules: Iterable[BasketRule],
    travel_matrix: TravelMatrix | None = None,
    metadata: Mapping[str, Any] | None = None,
    validate: bool = True,
) -> ScheduleBundle:
    bundle = ScheduleBundle(
        week_horizon=week_horizon,
        machines={machine.machine_id: machine for machine in machines},
        batches={batch.batch_id: batch for batch in batches},
        schedule_operations=tuple(schedule_operations),
        basket_rules={(rule.machine_id, rule.product_id): rule for rule in basket_rules},
        travel_matrix=travel_matrix or TravelMatrix(),
        metadata=metadata or {},
    )
    if validate:
        validate_schedule_bundle(bundle)
    return bundle
