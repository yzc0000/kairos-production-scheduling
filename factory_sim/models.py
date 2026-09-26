from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class DistributionSpec:
    kind: str
    parameters: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", self.kind.lower().strip())
        object.__setattr__(self, "parameters", dict(self.parameters))


@dataclass(frozen=True, slots=True)
class TimeWindow:
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("TimeWindow end must be greater than start.")

    def contains(self, moment: float) -> bool:
        return self.start <= moment < self.end


@dataclass(frozen=True, slots=True)
class Calendar:
    calendar_id: str
    working_windows: tuple[TimeWindow, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.working_windows, key=lambda window: (window.start, window.end)))
        for current, nxt in zip(ordered, ordered[1:]):
            if current.end - EPSILON > nxt.start:
                raise ValueError("Calendar windows must not overlap.")
        object.__setattr__(self, "working_windows", ordered)

    def is_working(self, moment: float) -> bool:
        return any(window.contains(moment) for window in self.working_windows)

    def next_work_start(self, moment: float) -> float | None:
        for window in self.working_windows:
            if window.contains(moment):
                return moment
            if window.start > moment:
                return window.start
        return None

    def current_window_end(self, moment: float) -> float | None:
        for window in self.working_windows:
            if window.contains(moment):
                return window.end
        return None


@dataclass(frozen=True, slots=True)
class FailureProfile:
    profile_id: str
    uptime_distribution: DistributionSpec | None = None
    repair_distribution: DistributionSpec | None = None


@dataclass(frozen=True, slots=True)
class Machine:
    machine_id: str
    calendar: Calendar
    fixed_setup_time: float = 0.0
    failure_profile: FailureProfile | None = None
    name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.fixed_setup_time < 0:
            raise ValueError("Machine fixed_setup_time must be non-negative.")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class RouteStep:
    step_id: str
    sequence: int
    process_time_per_unit: DistributionSpec
    predecessor_step_ids: tuple[str, ...] | None = None
    name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        predecessors = self.predecessor_step_ids
        if predecessors is None:
            object.__setattr__(self, "predecessor_step_ids", None)
        else:
            normalized = tuple(dict.fromkeys(predecessors))
            if self.step_id in normalized:
                raise ValueError("RouteStep cannot list itself as a predecessor.")
            object.__setattr__(self, "predecessor_step_ids", normalized)
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class Batch:
    batch_id: str
    product_id: str
    quantity: float
    route: tuple[RouteStep, ...]
    family_id: str | None = None
    release_time: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("Batch quantity must be positive.")
        if self.release_time < 0:
            raise ValueError("Batch release_time must be non-negative.")
        ordered_route = tuple(sorted(self.route, key=lambda step: step.sequence))
        if len({step.step_id for step in ordered_route}) != len(ordered_route):
            raise ValueError("Route step ids must be unique inside a batch route.")
        object.__setattr__(self, "route", ordered_route)
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def setup_key(self) -> str:
        return self.family_id or self.product_id


@dataclass(frozen=True, slots=True)
class ScheduleOperation:
    operation_id: str
    batch_id: str
    step_id: str
    machine_id: str
    machine_sequence: int
    planned_start: float
    planned_end: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.planned_end < self.planned_start:
            raise ValueError("ScheduleOperation planned_end must be >= planned_start.")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class BasketRule:
    machine_id: str
    product_id: str
    capacity_quantity: float

    def __post_init__(self) -> None:
        if self.capacity_quantity <= 0:
            raise ValueError("Basket capacity_quantity must be positive.")


@dataclass(frozen=True, slots=True)
class TravelMatrix:
    durations: Mapping[tuple[str, str], float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = dict(self.durations)
        for key, value in normalized.items():
            if value < 0:
                raise ValueError(f"Travel duration for {key!r} must be non-negative.")
        object.__setattr__(self, "durations", normalized)

    def get_duration(self, origin: str, destination: str) -> float:
        if origin == destination:
            return 0.0
        key = (origin, destination)
        if key not in self.durations:
            raise KeyError(f"Missing travel duration from {origin!r} to {destination!r}.")
        return self.durations[key]

    def has_duration(self, origin: str, destination: str) -> bool:
        return origin == destination or (origin, destination) in self.durations


@dataclass(frozen=True, slots=True)
class FailureSample:
    time_to_failure: float | None
    repair_time: float = 0.0

    def __post_init__(self) -> None:
        if self.time_to_failure is not None and self.time_to_failure < 0:
            raise ValueError("FailureSample time_to_failure must be non-negative or None.")
        if self.repair_time < 0:
            raise ValueError("FailureSample repair_time must be non-negative.")


@dataclass(frozen=True, slots=True)
class EventRecord:
    time: float
    event_type: str
    machine_id: str | None = None
    batch_id: str | None = None
    operation_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", dict(self.details))


@dataclass(frozen=True, slots=True)
class OperationResult:
    operation_id: str
    batch_id: str
    step_id: str
    machine_id: str
    planned_start: float
    planned_end: float
    setup_started_at: float | None = None
    actual_start: float | None = None
    actual_end: float | None = None
    release_time: float | None = None
    downstream_available_time: float | None = None
    successor_available_times: Mapping[str, float] = field(default_factory=dict)
    sampled_setup_time: float = 0.0
    sampled_process_time: float = 0.0
    status: str = "pending"


@dataclass(frozen=True, slots=True)
class InitialOperationState:
    operation_id: str
    status: str
    available_time: float | None = None
    setup_started_at: float | None = None
    actual_start: float | None = None
    actual_end: float | None = None
    release_time: float | None = None
    downstream_available_time: float | None = None
    successor_available_times: Mapping[str, float] = field(default_factory=dict)
    arrived_predecessor_ids: tuple[str, ...] = field(default_factory=tuple)
    sampled_setup_time: float = 0.0
    sampled_process_time: float = 0.0
    remaining_setup_time: float | None = None
    remaining_process_time: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "successor_available_times", dict(self.successor_available_times))
        object.__setattr__(self, "arrived_predecessor_ids", tuple(dict.fromkeys(self.arrived_predecessor_ids)))


@dataclass(frozen=True, slots=True)
class InitialBasketState:
    current_product_id: str | None = None
    quantity: float = 0.0
    operation_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_ids", tuple(dict.fromkeys(self.operation_ids)))


@dataclass(frozen=True, slots=True)
class InitialMachineState:
    machine_id: str
    last_batch_id: str | None = None
    last_operation_id: str | None = None
    next_failure_after_work: float | None = None
    next_repair_time: float = 0.0
    basket: InitialBasketState = field(default_factory=InitialBasketState)


@dataclass(frozen=True, slots=True)
class InitialTransferState:
    predecessor_operation_id: str
    successor_operation_id: str
    remaining_travel_time: float


@dataclass(frozen=True, slots=True)
class InitialSimulationState:
    start_time: float
    operations: Mapping[str, InitialOperationState] = field(default_factory=dict)
    machines: Mapping[str, InitialMachineState] = field(default_factory=dict)
    transfers: tuple[InitialTransferState, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operations", dict(self.operations))
        object.__setattr__(self, "machines", dict(self.machines))
        object.__setattr__(self, "transfers", tuple(self.transfers))


@dataclass(frozen=True, slots=True)
class MachineSummary:
    machine_id: str
    completed_operations: int
    productive_time: float
    setup_time: float
    downtime_time: float
    calendar_pause_time: float
    waiting_for_batch_time: float
    waiting_for_basket_time: float
    waiting_for_schedule_time: float
    idle_time: float
    blocked_time: float


@dataclass(frozen=True, slots=True)
class BatchSummary:
    batch_id: str
    product_id: str
    quantity: float
    completed: bool
    current_stage: str
    pending_operation_id: str | None = None
    current_machine_id: str | None = None
    finished_at: float | None = None


@dataclass(frozen=True, slots=True)
class SimulationResult:
    horizon: float
    operations: tuple[OperationResult, ...]
    events: tuple[EventRecord, ...]
    machine_summaries: tuple[MachineSummary, ...]
    batch_summaries: tuple[BatchSummary, ...]
    leftover_batches: tuple[BatchSummary, ...]


@dataclass(frozen=True, slots=True)
class ScheduleBundle:
    week_horizon: float
    machines: Mapping[str, Machine]
    batches: Mapping[str, Batch]
    schedule_operations: tuple[ScheduleOperation, ...]
    basket_rules: Mapping[tuple[str, str], BasketRule]
    travel_matrix: TravelMatrix = field(default_factory=TravelMatrix)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.week_horizon <= 0:
            raise ValueError("ScheduleBundle week_horizon must be positive.")
        object.__setattr__(self, "machines", dict(self.machines))
        object.__setattr__(self, "batches", dict(self.batches))
        object.__setattr__(self, "schedule_operations", tuple(self.schedule_operations))
        object.__setattr__(self, "basket_rules", dict(self.basket_rules))
        object.__setattr__(self, "metadata", dict(self.metadata))
