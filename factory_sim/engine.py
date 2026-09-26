from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .hooks import SimulationHooks
from .models import (
    Batch,
    BatchSummary,
    EPSILON,
    EventRecord,
    InitialSimulationState,
    Machine,
    MachineSummary,
    OperationResult,
    RouteStep,
    ScheduleBundle,
    ScheduleOperation,
    SimulationResult,
)
from .validation import group_operations_by_batch, resolve_step_predecessors, validate_schedule_bundle

if TYPE_CHECKING:
    import simpy


@dataclass(slots=True)
class _OperationRuntime:
    definition: ScheduleOperation
    batch: Batch
    route_step: RouteStep
    available_event: Any
    predecessor_runtimes: list["_OperationRuntime"] = field(default_factory=list)
    successor_runtimes: list["_OperationRuntime"] = field(default_factory=list)
    arrived_predecessor_ids: set[str] = field(default_factory=set)
    status: str = "pending"
    available_time: float | None = None
    setup_started_at: float | None = None
    actual_start: float | None = None
    actual_end: float | None = None
    release_time: float | None = None
    downstream_available_time: float | None = None
    successor_available_times: dict[str, float] = field(default_factory=dict)
    sampled_setup_time: float = 0.0
    sampled_process_time: float = 0.0
    remaining_setup_time: float | None = None
    remaining_process_time: float | None = None


@dataclass(slots=True)
class _BatchState:
    batch: Batch
    operation_by_step: dict[str, _OperationRuntime]
    ordered_operations: list[_OperationRuntime]
    root_operations: list[_OperationRuntime]
    terminal_operations: list[_OperationRuntime]
    completion_time: float | None = None


@dataclass(slots=True)
class _BasketState:
    changed_event: Any
    current_product_id: str | None = None
    quantity: float = 0.0
    operations: list[_OperationRuntime] = field(default_factory=list)

    def can_accept(self, product_id: str) -> bool:
        return self.current_product_id is None or self.current_product_id == product_id


@dataclass(slots=True)
class _MachineState:
    machine: Machine
    operations: list[_OperationRuntime]
    basket: _BasketState
    last_batch: Batch | None = None
    last_operation: _OperationRuntime | None = None
    next_failure_after_work: float | None = None
    next_repair_time: float = 0.0
    completed_operations: int = 0
    productive_time: float = 0.0
    setup_time: float = 0.0
    downtime_time: float = 0.0
    calendar_pause_time: float = 0.0
    waiting_for_batch_time: float = 0.0
    waiting_for_basket_time: float = 0.0
    waiting_for_schedule_time: float = 0.0

    @property
    def idle_time(self) -> float:
        return (
            self.waiting_for_batch_time
            + self.waiting_for_basket_time
            + self.waiting_for_schedule_time
        )

    @property
    def blocked_time(self) -> float:
        return self.waiting_for_basket_time


def run_week(
    schedule_bundle: ScheduleBundle,
    seed: int,
    hooks: SimulationHooks | None = None,
    trace: bool = True,
    initial_state: InitialSimulationState | None = None,
) -> SimulationResult:
    try:
        import simpy
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "simpy is required to run the simulation. Install project dependencies first."
        ) from exc

    validate_schedule_bundle(schedule_bundle)
    hooks = hooks or SimulationHooks()
    rng = random.Random(seed)
    env = simpy.Environment(initial_time=initial_state.start_time if initial_state is not None else 0.0)
    horizon = schedule_bundle.week_horizon
    events: list[EventRecord] = []

    batch_states = _build_batch_states(env, schedule_bundle)
    machine_states = _build_machine_states(env, schedule_bundle, batch_states, hooks, rng)
    if initial_state is not None:
        _apply_initial_state(
            env=env,
            initial_state=initial_state,
            batch_states=batch_states,
            machine_states=machine_states,
            bundle=schedule_bundle,
            horizon=horizon,
            events=events,
            hooks=hooks,
            trace=trace,
        )

    for batch_state in batch_states.values():
        env.process(
            _release_batch_roots(
                env=env,
                batch_state=batch_state,
                horizon=horizon,
                events=events,
                hooks=hooks,
                trace=trace,
            )
        )

    for machine_state in machine_states.values():
        env.process(
            _machine_runner(
                env=env,
                machine_state=machine_state,
                batch_states=batch_states,
                horizon=horizon,
                bundle=schedule_bundle,
                hooks=hooks,
                rng=rng,
                events=events,
                trace=trace,
            )
        )

    env.run(until=horizon)
    return _build_result(schedule_bundle, machine_states, batch_states, events)


def _build_batch_states(
    env: "simpy.Environment",
    bundle: ScheduleBundle,
) -> dict[str, _BatchState]:
    operations_by_batch = group_operations_by_batch(bundle)
    batch_states: dict[str, _BatchState] = {}
    for batch_id, operations in operations_by_batch.items():
        batch = bundle.batches[batch_id]
        route_lookup = {step.step_id: step for step in batch.route}
        predecessor_map = resolve_step_predecessors(batch)
        ordered_operations = [
            _OperationRuntime(
                definition=operation,
                batch=batch,
                route_step=route_lookup[operation.step_id],
                available_event=env.event(),
            )
            for operation in operations
        ]
        operation_by_step = {
            runtime.definition.step_id: runtime for runtime in ordered_operations
        }
        for runtime in ordered_operations:
            for predecessor_step_id in predecessor_map[runtime.definition.step_id]:
                predecessor_runtime = operation_by_step[predecessor_step_id]
                runtime.predecessor_runtimes.append(predecessor_runtime)
                predecessor_runtime.successor_runtimes.append(runtime)

        batch_states[batch_id] = _BatchState(
            batch=batch,
            operation_by_step=operation_by_step,
            ordered_operations=ordered_operations,
            root_operations=[runtime for runtime in ordered_operations if not runtime.predecessor_runtimes],
            terminal_operations=[runtime for runtime in ordered_operations if not runtime.successor_runtimes],
        )
    return batch_states


def _build_machine_states(
    env: "simpy.Environment",
    bundle: ScheduleBundle,
    batch_states: dict[str, _BatchState],
    hooks: SimulationHooks,
    rng: random.Random,
) -> dict[str, _MachineState]:
    runtimes_by_machine: dict[str, list[_OperationRuntime]] = defaultdict(list)
    runtime_lookup = {
        runtime.definition.operation_id: runtime
        for batch_state in batch_states.values()
        for runtime in batch_state.ordered_operations
    }
    for operation in bundle.schedule_operations:
        runtimes_by_machine[operation.machine_id].append(runtime_lookup[operation.operation_id])

    machine_states: dict[str, _MachineState] = {}
    for machine_id, machine in bundle.machines.items():
        operations = sorted(
            runtimes_by_machine.get(machine_id, []),
            key=lambda runtime: runtime.definition.machine_sequence,
        )
        machine_state = _MachineState(
            machine=machine,
            operations=operations,
            basket=_BasketState(changed_event=env.event()),
        )
        _sample_next_failure(machine_state, hooks, rng)
        machine_states[machine_id] = machine_state
    return machine_states


def _apply_initial_state(
    env: "simpy.Environment",
    initial_state: InitialSimulationState,
    batch_states: dict[str, _BatchState],
    machine_states: dict[str, _MachineState],
    bundle: ScheduleBundle,
    horizon: float,
    events: list[EventRecord],
    hooks: SimulationHooks,
    trace: bool,
) -> None:
    runtime_lookup = {
        runtime.definition.operation_id: runtime
        for batch_state in batch_states.values()
        for runtime in batch_state.ordered_operations
    }

    for operation_id, state in initial_state.operations.items():
        runtime = runtime_lookup[operation_id]
        runtime.status = state.status
        runtime.available_time = state.available_time
        runtime.setup_started_at = state.setup_started_at
        runtime.actual_start = state.actual_start
        runtime.actual_end = state.actual_end
        runtime.release_time = state.release_time
        runtime.downstream_available_time = state.downstream_available_time
        runtime.successor_available_times = dict(state.successor_available_times)
        runtime.arrived_predecessor_ids = set(state.arrived_predecessor_ids)
        runtime.sampled_setup_time = state.sampled_setup_time
        runtime.sampled_process_time = state.sampled_process_time
        runtime.remaining_setup_time = state.remaining_setup_time
        runtime.remaining_process_time = state.remaining_process_time

        if (
            state.available_time is not None
            or state.status in {"available", "in_setup", "in_process", "waiting_in_basket", "released", "completed"}
        ) and not runtime.available_event.triggered:
            runtime.available_event.succeed(state.available_time if state.available_time is not None else env.now)

    for machine_id, state in initial_state.machines.items():
        machine_state = machine_states[machine_id]
        if state.last_batch_id is not None:
            machine_state.last_batch = bundle.batches[state.last_batch_id]
        if state.last_operation_id is not None:
            machine_state.last_operation = runtime_lookup[state.last_operation_id]
        machine_state.next_failure_after_work = state.next_failure_after_work
        machine_state.next_repair_time = state.next_repair_time
        machine_state.basket.current_product_id = state.basket.current_product_id
        machine_state.basket.quantity = state.basket.quantity
        machine_state.basket.operations = [
            runtime_lookup[operation_id] for operation_id in state.basket.operation_ids
        ]

    for transfer in initial_state.transfers:
        predecessor_runtime = runtime_lookup[transfer.predecessor_operation_id]
        successor_runtime = runtime_lookup[transfer.successor_operation_id]
        env.process(
            _transfer_to_successor(
                env=env,
                predecessor_runtime=predecessor_runtime,
                successor_runtime=successor_runtime,
                travel_time=transfer.remaining_travel_time,
                horizon=horizon,
                events=events,
                hooks=hooks,
                trace=trace,
            )
        )

    for batch_state in batch_states.values():
        if batch_state.terminal_operations and all(
            runtime.release_time is not None and runtime.release_time <= env.now
            for runtime in batch_state.terminal_operations
        ):
            batch_state.completion_time = max(
                runtime.release_time for runtime in batch_state.terminal_operations if runtime.release_time is not None
            )


def _release_batch_roots(
    env: "simpy.Environment",
    batch_state: _BatchState,
    horizon: float,
    events: list[EventRecord],
    hooks: SimulationHooks,
    trace: bool,
):
    root_groups: dict[float, list[_OperationRuntime]] = defaultdict(list)
    for runtime in batch_state.root_operations:
        if runtime.available_event.triggered or runtime.actual_start is not None or runtime.actual_end is not None:
            continue
        release_time = float(runtime.definition.metadata.get("release_time", batch_state.batch.release_time))
        root_groups[release_time].append(runtime)

    for release_time, runtimes in sorted(root_groups.items(), key=lambda item: item[0]):
        if release_time > env.now:
            yield env.timeout(min(release_time - env.now, max(0.0, horizon - env.now)))
        if env.now + EPSILON >= horizon:
            return

        _record_event(
            events,
            hooks,
            trace,
            time=env.now,
            event_type="batch_released",
            batch_id=batch_state.batch.batch_id,
            root_operation_ids=[runtime.definition.operation_id for runtime in runtimes],
        )
        for runtime in runtimes:
            _mark_operation_available(
                env=env,
                runtime=runtime,
                events=events,
                hooks=hooks,
                trace=trace,
                reason="batch_release",
            )


def _mark_operation_available(
    env: "simpy.Environment",
    runtime: _OperationRuntime,
    events: list[EventRecord],
    hooks: SimulationHooks,
    trace: bool,
    reason: str,
    predecessor_operation_id: str | None = None,
) -> None:
    if runtime.available_event.triggered:
        return
    runtime.available_time = env.now
    runtime.status = "available"
    runtime.available_event.succeed(env.now)
    _record_event(
        events,
        hooks,
        trace,
        time=env.now,
        event_type="operation_available",
        machine_id=runtime.definition.machine_id,
        batch_id=runtime.batch.batch_id,
        operation_id=runtime.definition.operation_id,
        reason=reason,
        predecessor_operation_id=predecessor_operation_id,
    )


def _machine_runner(
    env: "simpy.Environment",
    machine_state: _MachineState,
    batch_states: dict[str, _BatchState],
    horizon: float,
    bundle: ScheduleBundle,
    hooks: SimulationHooks,
    rng: random.Random,
    events: list[EventRecord],
    trace: bool,
):
    for operation_runtime in machine_state.operations:
        if env.now + EPSILON >= horizon:
            break
        if operation_runtime.actual_end is not None:
            continue
        if operation_runtime.status in {"released", "completed"}:
            continue

        allow_setup_before_availability = hooks.setup_before_availability(
            machine_state.machine,
            operation_runtime.definition,
            operation_runtime.batch,
        )
        if (
            not operation_runtime.available_event.triggered
            and not allow_setup_before_availability
        ):
            idle_reason = _availability_idle_reason(operation_runtime, after_setup=False)
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="idle_started",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                idle_reason=idle_reason,
            )
            wait_start = env.now
            available = yield from _wait_for_event_or_horizon(env, operation_runtime.available_event, horizon)
            wait_duration = env.now - wait_start
            machine_state.waiting_for_batch_time += wait_duration
            if wait_duration > EPSILON:
                _record_event(
                    events,
                    hooks,
                    trace,
                    time=env.now,
                    event_type="idle_ended",
                    machine_id=machine_state.machine.machine_id,
                    batch_id=operation_runtime.batch.batch_id,
                    operation_id=operation_runtime.definition.operation_id,
                    idle_reason=idle_reason,
                    duration=wait_duration,
                )
            if not available:
                break

        while not machine_state.basket.can_accept(operation_runtime.batch.product_id):
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="idle_started",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                idle_reason="basket_blocked",
            )
            wait_start = env.now
            available = yield from _wait_for_event_or_horizon(env, machine_state.basket.changed_event, horizon)
            wait_duration = env.now - wait_start
            machine_state.waiting_for_basket_time += wait_duration
            if wait_duration > EPSILON:
                _record_event(
                    events,
                    hooks,
                    trace,
                    time=env.now,
                    event_type="idle_ended",
                    machine_id=machine_state.machine.machine_id,
                    batch_id=operation_runtime.batch.batch_id,
                    operation_id=operation_runtime.definition.operation_id,
                    idle_reason="basket_blocked",
                    duration=wait_duration,
                )
            if not available:
                return

        resumed_setup = operation_runtime.setup_started_at is not None and operation_runtime.actual_start is None
        if resumed_setup:
            setup_time = (
                operation_runtime.remaining_setup_time
                if operation_runtime.remaining_setup_time is not None
                else operation_runtime.sampled_setup_time
            )
        else:
            setup_time = hooks.setup_time(
                machine_state.machine,
                machine_state.last_operation.definition if machine_state.last_operation is not None else None,
                machine_state.last_batch,
                operation_runtime.definition,
                operation_runtime.batch,
            )
            operation_runtime.sampled_setup_time = setup_time

        earliest_setup_start = env.now if resumed_setup else hooks.earliest_setup_start(
            machine_state.machine,
            operation_runtime.definition,
            operation_runtime.batch,
            setup_time,
        )
        if not resumed_setup and earliest_setup_start > env.now + EPSILON:
            wait_duration = min(earliest_setup_start, horizon) - env.now
            if wait_duration <= EPSILON:
                return
            machine_state.waiting_for_schedule_time += wait_duration
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="idle_started",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                idle_reason="schedule_hold",
            )
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="schedule_hold_started",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                duration=wait_duration,
                earliest_setup_start=earliest_setup_start,
            )
            yield env.timeout(wait_duration)
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="idle_ended",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                idle_reason="schedule_hold",
                duration=wait_duration,
            )
            if env.now + EPSILON >= horizon:
                return
        if setup_time > 0:
            if operation_runtime.setup_started_at is None:
                operation_runtime.setup_started_at = env.now
            operation_runtime.status = "in_setup"
            if not resumed_setup:
                _record_event(
                    events,
                    hooks,
                    trace,
                    time=env.now,
                    event_type="setup_started",
                    machine_id=machine_state.machine.machine_id,
                    batch_id=operation_runtime.batch.batch_id,
                    operation_id=operation_runtime.definition.operation_id,
                    setup_time=setup_time,
                )
            completed = yield from _consume_active_time(
                env=env,
                machine_state=machine_state,
                horizon=horizon,
                hooks=hooks,
                rng=rng,
                events=events,
                trace=trace,
                operation_runtime=operation_runtime,
                amount=setup_time,
                phase="setup",
            )
            if not completed:
                return
            operation_runtime.remaining_setup_time = 0.0
        if not operation_runtime.available_event.triggered:
            idle_reason = _availability_idle_reason(operation_runtime, after_setup=True)
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="idle_started",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                idle_reason=idle_reason,
            )
            wait_start = env.now
            available = yield from _wait_for_event_or_horizon(env, operation_runtime.available_event, horizon)
            wait_duration = env.now - wait_start
            machine_state.waiting_for_batch_time += wait_duration
            if wait_duration > EPSILON:
                _record_event(
                    events,
                    hooks,
                    trace,
                    time=env.now,
                    event_type="idle_ended",
                    machine_id=machine_state.machine.machine_id,
                    batch_id=operation_runtime.batch.batch_id,
                    operation_id=operation_runtime.definition.operation_id,
                    idle_reason=idle_reason,
                    duration=wait_duration,
                )
            if not available:
                return

        resumed_processing = operation_runtime.actual_start is not None and operation_runtime.actual_end is None
        if operation_runtime.actual_start is None:
            operation_runtime.actual_start = env.now
        operation_runtime.status = "in_process"
        if resumed_processing:
            process_amount = (
                operation_runtime.remaining_process_time
                if operation_runtime.remaining_process_time is not None
                else operation_runtime.sampled_process_time
            )
        else:
            operation_runtime.sampled_process_time = hooks.process_time(
                machine_state.machine,
                operation_runtime.batch,
                operation_runtime.route_step,
                operation_runtime.definition,
                rng,
            )
            process_amount = operation_runtime.sampled_process_time
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="processing_started",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                process_time=operation_runtime.sampled_process_time,
            )
        completed = yield from _consume_active_time(
            env=env,
            machine_state=machine_state,
            horizon=horizon,
            hooks=hooks,
            rng=rng,
            events=events,
            trace=trace,
            operation_runtime=operation_runtime,
            amount=process_amount,
            phase="processing",
        )
        if not completed:
            return

        operation_runtime.actual_end = env.now
        operation_runtime.remaining_process_time = 0.0
        operation_runtime.status = "waiting_in_basket"
        machine_state.completed_operations += 1
        machine_state.last_batch = operation_runtime.batch
        machine_state.last_operation = operation_runtime
        _record_event(
            events,
            hooks,
            trace,
            time=env.now,
            event_type="processing_completed",
            machine_id=machine_state.machine.machine_id,
            batch_id=operation_runtime.batch.batch_id,
            operation_id=operation_runtime.definition.operation_id,
        )
        _add_to_basket(machine_state, operation_runtime)
        _maybe_release_basket(
            env=env,
            machine_state=machine_state,
            batch_states=batch_states,
            horizon=horizon,
            hooks=hooks,
            bundle=bundle,
            events=events,
            trace=trace,
        )


def _sample_next_failure(machine_state: _MachineState, hooks: SimulationHooks, rng: random.Random) -> None:
    sample = hooks.failure(machine_state.machine, rng)
    machine_state.next_failure_after_work = sample.time_to_failure
    machine_state.next_repair_time = sample.repair_time


def _wait_for_event_or_horizon(env: "simpy.Environment", event: Any, horizon: float):
    remaining = horizon - env.now
    if remaining <= EPSILON:
        return False
    timeout_event = env.timeout(remaining)
    result = yield event | timeout_event
    return event in result


def _consume_active_time(
    env: "simpy.Environment",
    machine_state: _MachineState,
    horizon: float,
    hooks: SimulationHooks,
    rng: random.Random,
    events: list[EventRecord],
    trace: bool,
    operation_runtime: _OperationRuntime,
    amount: float,
    phase: str,
):
    remaining = amount
    while remaining > EPSILON:
        if env.now + EPSILON >= horizon:
            _store_remaining_active_time(operation_runtime, phase, remaining)
            return False

        next_start = machine_state.machine.calendar.next_work_start(env.now)
        if next_start is None:
            if env.now + EPSILON < horizon:
                machine_state.calendar_pause_time += horizon - env.now
                yield env.timeout(horizon - env.now)
            _store_remaining_active_time(operation_runtime, phase, remaining)
            return False
        if next_start > env.now + EPSILON:
            pause_duration = min(next_start, horizon) - env.now
            if pause_duration <= EPSILON:
                _store_remaining_active_time(operation_runtime, phase, remaining)
                return False
            machine_state.calendar_pause_time += pause_duration
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="shift_pause_started",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                phase=phase,
                duration=pause_duration,
            )
            yield env.timeout(pause_duration)
            if env.now + EPSILON >= horizon:
                _store_remaining_active_time(operation_runtime, phase, remaining)
                return False

        window_end = machine_state.machine.calendar.current_window_end(env.now)
        if window_end is None:
            continue
        available_duration = min(window_end, horizon) - env.now
        if available_duration <= EPSILON:
            continue

        work_chunk = min(remaining, available_duration)
        if machine_state.next_failure_after_work is not None:
            work_chunk = min(work_chunk, machine_state.next_failure_after_work)
        if work_chunk <= EPSILON:
            work_chunk = 0.0

        if work_chunk > 0:
            yield env.timeout(work_chunk)
            remaining -= work_chunk
            if phase == "setup":
                machine_state.setup_time += work_chunk
            else:
                machine_state.productive_time += work_chunk
            if machine_state.next_failure_after_work is not None:
                machine_state.next_failure_after_work -= work_chunk

        failure_due = (
            remaining > EPSILON
            and machine_state.next_failure_after_work is not None
            and machine_state.next_failure_after_work <= EPSILON
            and env.now + EPSILON < window_end
            and env.now + EPSILON < horizon
        )
        if failure_due:
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="breakdown_started",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                phase=phase,
            )
            repair_duration = min(machine_state.next_repair_time, max(0.0, horizon - env.now))
            machine_state.downtime_time += repair_duration
            if repair_duration > 0:
                yield env.timeout(repair_duration)
            if env.now + EPSILON >= horizon:
                _store_remaining_active_time(operation_runtime, phase, remaining)
                return False
            _record_event(
                events,
                hooks,
                trace,
                time=env.now,
                event_type="breakdown_ended",
                machine_id=machine_state.machine.machine_id,
                batch_id=operation_runtime.batch.batch_id,
                operation_id=operation_runtime.definition.operation_id,
                phase=phase,
            )
            _sample_next_failure(machine_state, hooks, rng)
            continue

        if remaining > EPSILON and env.now + EPSILON >= window_end:
            continue

    return True


def _store_remaining_active_time(operation_runtime: _OperationRuntime, phase: str, remaining: float) -> None:
    if phase == "setup":
        operation_runtime.remaining_setup_time = max(0.0, remaining)
    else:
        operation_runtime.remaining_process_time = max(0.0, remaining)


def _add_to_basket(machine_state: _MachineState, operation_runtime: _OperationRuntime) -> None:
    basket = machine_state.basket
    product_id = operation_runtime.batch.product_id
    if basket.current_product_id is None:
        basket.current_product_id = product_id
    basket.quantity += operation_runtime.batch.quantity
    basket.operations.append(operation_runtime)


def _maybe_release_basket(
    env: "simpy.Environment",
    machine_state: _MachineState,
    batch_states: dict[str, _BatchState],
    horizon: float,
    hooks: SimulationHooks,
    bundle: ScheduleBundle,
    events: list[EventRecord],
    trace: bool,
) -> None:
    basket = machine_state.basket
    if basket.current_product_id is None:
        return
    rule = bundle.basket_rules[(machine_state.machine.machine_id, basket.current_product_id)]
    should_release = hooks.basket_release(
        machine_state.machine,
        basket.current_product_id,
        basket.quantity,
        rule.capacity_quantity,
    )
    if not should_release:
        return

    released_operations = list(basket.operations)
    released_quantity = basket.quantity
    product_id = basket.current_product_id
    basket.current_product_id = None
    basket.quantity = 0.0
    basket.operations = []
    previous_event = basket.changed_event
    basket.changed_event = env.event()
    if not previous_event.triggered:
        previous_event.succeed(env.now)

    _record_event(
        events,
        hooks,
        trace,
        time=env.now,
        event_type="basket_released",
        machine_id=machine_state.machine.machine_id,
        product_id=product_id,
        released_quantity=released_quantity,
        released_operations=len(released_operations),
    )

    touched_batch_ids: set[str] = set()
    for operation_runtime in released_operations:
        touched_batch_ids.add(operation_runtime.batch.batch_id)
        operation_runtime.release_time = env.now
        if not operation_runtime.successor_runtimes:
            operation_runtime.downstream_available_time = env.now
            operation_runtime.status = "completed"
        else:
            operation_runtime.status = "released"
            for successor_runtime in operation_runtime.successor_runtimes:
                travel_time = bundle.travel_matrix.get_duration(
                    operation_runtime.definition.machine_id,
                    successor_runtime.definition.machine_id,
                )
                _record_event(
                    events,
                    hooks,
                    trace,
                    time=env.now,
                    event_type="transfer_started",
                    machine_id=machine_state.machine.machine_id,
                    batch_id=operation_runtime.batch.batch_id,
                    operation_id=operation_runtime.definition.operation_id,
                    next_machine_id=successor_runtime.definition.machine_id,
                    next_operation_id=successor_runtime.definition.operation_id,
                    travel_time=travel_time,
                )
                env.process(
                    _transfer_to_successor(
                        env=env,
                        predecessor_runtime=operation_runtime,
                        successor_runtime=successor_runtime,
                        travel_time=travel_time,
                        horizon=horizon,
                        events=events,
                        hooks=hooks,
                        trace=trace,
                    )
                )

    for batch_id in touched_batch_ids:
        _finalize_batch_if_complete(
            batch_state=batch_states[batch_id],
            completion_time=env.now,
            events=events,
            hooks=hooks,
            trace=trace,
        )


def _transfer_to_successor(
    env: "simpy.Environment",
    predecessor_runtime: _OperationRuntime,
    successor_runtime: _OperationRuntime,
    travel_time: float,
    horizon: float,
    events: list[EventRecord],
    hooks: SimulationHooks,
    trace: bool,
):
    if travel_time > 0:
        yield env.timeout(min(travel_time, max(0.0, horizon - env.now)))
    if env.now + EPSILON >= horizon:
        return

    predecessor_runtime.successor_available_times[successor_runtime.definition.operation_id] = env.now
    predecessor_runtime.downstream_available_time = max(predecessor_runtime.successor_available_times.values())
    successor_runtime.arrived_predecessor_ids.add(predecessor_runtime.definition.operation_id)
    _record_event(
        events,
        hooks,
        trace,
        time=env.now,
        event_type="transfer_completed",
        machine_id=successor_runtime.definition.machine_id,
        batch_id=successor_runtime.batch.batch_id,
        operation_id=successor_runtime.definition.operation_id,
        predecessor_operation_id=predecessor_runtime.definition.operation_id,
    )
    if len(successor_runtime.arrived_predecessor_ids) == len(successor_runtime.predecessor_runtimes):
        _mark_operation_available(
            env=env,
            runtime=successor_runtime,
            events=events,
            hooks=hooks,
            trace=trace,
            reason="predecessors_satisfied",
            predecessor_operation_id=predecessor_runtime.definition.operation_id,
        )


def _finalize_batch_if_complete(
    batch_state: _BatchState,
    completion_time: float,
    events: list[EventRecord],
    hooks: SimulationHooks,
    trace: bool,
) -> None:
    if batch_state.completion_time is not None:
        return
    if not batch_state.terminal_operations:
        return
    if any(runtime.release_time is None for runtime in batch_state.terminal_operations):
        return
    batch_state.completion_time = completion_time
    _record_event(
        events,
        hooks,
        trace,
        time=completion_time,
        event_type="batch_completed",
        batch_id=batch_state.batch.batch_id,
    )


def _record_event(
    events: list[EventRecord],
    hooks: SimulationHooks,
    trace: bool,
    time: float,
    event_type: str,
    machine_id: str | None = None,
    batch_id: str | None = None,
    operation_id: str | None = None,
    **details: Any,
) -> None:
    if not trace:
        return
    event = EventRecord(
        time=time,
        event_type=event_type,
        machine_id=machine_id,
        batch_id=batch_id,
        operation_id=operation_id,
        details=details,
    )
    events.append(hooks.event_formatter(event))


def _availability_idle_reason(runtime: _OperationRuntime, after_setup: bool) -> str:
    if runtime.predecessor_runtimes:
        return "waiting_for_predecessors_after_setup" if after_setup else "waiting_for_predecessors"
    return "waiting_for_release_after_setup" if after_setup else "waiting_for_release"


def _build_result(
    bundle: ScheduleBundle,
    machine_states: dict[str, _MachineState],
    batch_states: dict[str, _BatchState],
    events: list[EventRecord],
) -> SimulationResult:
    runtime_lookup = {
        runtime.definition.operation_id: runtime
        for batch_state in batch_states.values()
        for runtime in batch_state.ordered_operations
    }
    operation_results = tuple(
        OperationResult(
            operation_id=operation.operation_id,
            batch_id=runtime_lookup[operation.operation_id].batch.batch_id,
            step_id=runtime_lookup[operation.operation_id].definition.step_id,
            machine_id=runtime_lookup[operation.operation_id].definition.machine_id,
            planned_start=runtime_lookup[operation.operation_id].definition.planned_start,
            planned_end=runtime_lookup[operation.operation_id].definition.planned_end,
            setup_started_at=runtime_lookup[operation.operation_id].setup_started_at,
            actual_start=runtime_lookup[operation.operation_id].actual_start,
            actual_end=runtime_lookup[operation.operation_id].actual_end,
            release_time=runtime_lookup[operation.operation_id].release_time,
            downstream_available_time=runtime_lookup[operation.operation_id].downstream_available_time,
            successor_available_times=dict(runtime_lookup[operation.operation_id].successor_available_times),
            sampled_setup_time=runtime_lookup[operation.operation_id].sampled_setup_time,
            sampled_process_time=runtime_lookup[operation.operation_id].sampled_process_time,
            status=runtime_lookup[operation.operation_id].status,
        )
        for operation in bundle.schedule_operations
    )

    machine_summaries = tuple(
        MachineSummary(
            machine_id=machine_id,
            completed_operations=machine_state.completed_operations,
            productive_time=machine_state.productive_time,
            setup_time=machine_state.setup_time,
            downtime_time=machine_state.downtime_time,
            calendar_pause_time=machine_state.calendar_pause_time,
            waiting_for_batch_time=machine_state.waiting_for_batch_time,
            waiting_for_basket_time=machine_state.waiting_for_basket_time,
            waiting_for_schedule_time=machine_state.waiting_for_schedule_time,
            idle_time=machine_state.idle_time,
            blocked_time=machine_state.blocked_time,
        )
        for machine_id, machine_state in sorted(machine_states.items())
    )

    batch_summaries = tuple(
        _build_batch_summary(batch_state)
        for _, batch_state in sorted(batch_states.items(), key=lambda item: item[0])
    )
    leftover_batches = tuple(summary for summary in batch_summaries if not summary.completed)

    return SimulationResult(
        horizon=bundle.week_horizon,
        operations=operation_results,
        events=tuple(sorted(events, key=lambda event: (event.time, event.event_type))),
        machine_summaries=machine_summaries,
        batch_summaries=batch_summaries,
        leftover_batches=leftover_batches,
    )


def _build_batch_summary(batch_state: _BatchState) -> BatchSummary:
    batch = batch_state.batch
    if batch_state.completion_time is not None:
        return BatchSummary(
            batch_id=batch.batch_id,
            product_id=batch.product_id,
            quantity=batch.quantity,
            completed=True,
            current_stage="completed",
            finished_at=batch_state.completion_time,
        )

    for runtime in batch_state.ordered_operations:
        if runtime.setup_started_at is not None and runtime.actual_start is None:
            return BatchSummary(
                batch_id=batch.batch_id,
                product_id=batch.product_id,
                quantity=batch.quantity,
                completed=False,
                current_stage="in_setup",
                pending_operation_id=runtime.definition.operation_id,
                current_machine_id=runtime.definition.machine_id,
            )
        if runtime.actual_start is not None and runtime.actual_end is None:
            return BatchSummary(
                batch_id=batch.batch_id,
                product_id=batch.product_id,
                quantity=batch.quantity,
                completed=False,
                current_stage="in_process",
                pending_operation_id=runtime.definition.operation_id,
                current_machine_id=runtime.definition.machine_id,
            )
        if runtime.actual_end is not None and runtime.release_time is None:
            return BatchSummary(
                batch_id=batch.batch_id,
                product_id=batch.product_id,
                quantity=batch.quantity,
                completed=False,
                current_stage="waiting_in_basket",
                pending_operation_id=runtime.definition.operation_id,
                current_machine_id=runtime.definition.machine_id,
            )
        if runtime.available_time is not None and runtime.actual_start is None:
            return BatchSummary(
                batch_id=batch.batch_id,
                product_id=batch.product_id,
                quantity=batch.quantity,
                completed=False,
                current_stage="waiting_for_machine",
                pending_operation_id=runtime.definition.operation_id,
                current_machine_id=runtime.definition.machine_id,
            )
        if runtime.predecessor_runtimes and len(runtime.arrived_predecessor_ids) < len(runtime.predecessor_runtimes):
            return BatchSummary(
                batch_id=batch.batch_id,
                product_id=batch.product_id,
                quantity=batch.quantity,
                completed=False,
                current_stage="waiting_for_predecessors",
                pending_operation_id=runtime.definition.operation_id,
                current_machine_id=runtime.definition.machine_id,
            )

    return BatchSummary(
        batch_id=batch.batch_id,
        product_id=batch.product_id,
        quantity=batch.quantity,
        completed=False,
        current_stage="not_released",
        pending_operation_id=batch_state.root_operations[0].definition.operation_id if batch_state.root_operations else None,
        current_machine_id=batch_state.root_operations[0].definition.machine_id if batch_state.root_operations else None,
    )
