from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from .models import (
    Batch,
    DistributionSpec,
    EventRecord,
    FailureSample,
    Machine,
    RouteStep,
    ScheduleOperation,
)


def sample_distribution(spec: DistributionSpec, rng: random.Random) -> float:
    kind = spec.kind
    params = spec.parameters
    if kind == "deterministic":
        return float(params.get("value", 0.0))
    if kind == "uniform":
        return rng.uniform(float(params["low"]), float(params["high"]))
    if kind == "triangular":
        mode = params.get("mode")
        return rng.triangular(float(params["low"]), float(params["high"]), None if mode is None else float(mode))
    if kind == "normal":
        return max(0.0, rng.gauss(float(params["mean"]), float(params["stdev"])))
    if kind == "lognormal":
        return rng.lognormvariate(float(params["mean"]), float(params["sigma"]))
    if kind == "exponential":
        mean = float(params["mean"])
        if mean <= 0:
            raise ValueError("Exponential distribution mean must be positive.")
        return rng.expovariate(1.0 / mean)
    raise ValueError(f"Unsupported distribution kind: {spec.kind!r}.")


SetupTimeHook = Callable[[Machine, ScheduleOperation | None, Batch | None, ScheduleOperation, Batch], float]
ProcessTimeHook = Callable[[Machine, Batch, RouteStep, ScheduleOperation, random.Random], float]
FailureHook = Callable[[Machine, random.Random], FailureSample]
BasketReleaseHook = Callable[[Machine, str, float, float], bool]
EventFormatterHook = Callable[[EventRecord], EventRecord]
EarliestSetupStartHook = Callable[[Machine, ScheduleOperation, Batch, float], float]
SetupBeforeAvailabilityHook = Callable[[Machine, ScheduleOperation, Batch], bool]


def default_setup_time_hook(
    machine: Machine,
    previous_operation: ScheduleOperation | None,
    previous_batch: Batch | None,
    operation: ScheduleOperation,
    current_batch: Batch,
) -> float:
    if previous_batch is None:
        return 0.0
    return machine.fixed_setup_time if previous_batch.setup_key != current_batch.setup_key else 0.0


def default_process_time_hook(
    machine: Machine,
    batch: Batch,
    route_step: RouteStep,
    operation: ScheduleOperation,
    rng: random.Random,
) -> float:
    return sample_distribution(route_step.process_time_per_unit, rng) * batch.quantity


def default_failure_hook(machine: Machine, rng: random.Random) -> FailureSample:
    if machine.failure_profile is None or machine.failure_profile.uptime_distribution is None:
        return FailureSample(time_to_failure=None, repair_time=0.0)
    time_to_failure = sample_distribution(machine.failure_profile.uptime_distribution, rng)
    repair_distribution = machine.failure_profile.repair_distribution
    repair_time = sample_distribution(repair_distribution, rng) if repair_distribution is not None else 0.0
    return FailureSample(time_to_failure=time_to_failure, repair_time=repair_time)


def default_basket_release_hook(
    machine: Machine,
    product_id: str,
    basket_quantity: float,
    capacity_quantity: float,
) -> bool:
    return basket_quantity >= capacity_quantity


def default_event_formatter(event: EventRecord) -> EventRecord:
    return event


def default_earliest_setup_start_hook(
    machine: Machine,
    operation: ScheduleOperation,
    batch: Batch,
    setup_time: float,
) -> float:
    return 0.0


def default_setup_before_availability_hook(
    machine: Machine,
    operation: ScheduleOperation,
    batch: Batch,
) -> bool:
    return False


@dataclass(frozen=True, slots=True)
class SimulationHooks:
    setup_time: SetupTimeHook = default_setup_time_hook
    process_time: ProcessTimeHook = default_process_time_hook
    failure: FailureHook = default_failure_hook
    basket_release: BasketReleaseHook = default_basket_release_hook
    event_formatter: EventFormatterHook = default_event_formatter
    earliest_setup_start: EarliestSetupStartHook = default_earliest_setup_start_hook
    setup_before_availability: SetupBeforeAvailabilityHook = default_setup_before_availability_hook
