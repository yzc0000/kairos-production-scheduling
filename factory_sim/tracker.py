from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .models import EventRecord, ScheduleBundle, SimulationResult


_AVAILABILITY_REASON_LABELS = {
    "batch_release": "batch release",
    "predecessors_satisfied": "all predecessors arrived",
}

_IDLE_REASON_LABELS = {
    "waiting_for_release": "waiting for batch release",
    "waiting_for_predecessors": "waiting for predecessor completion",
    "basket_blocked": "waiting for the machine basket to clear",
    "schedule_hold": "waiting for the planned schedule window",
    "waiting_for_release_after_setup": "waiting for batch release after setup",
    "waiting_for_predecessors_after_setup": "waiting for predecessors after setup",
}


def build_product_tracker_lines(
    schedule_bundle: ScheduleBundle,
    simulation_result: SimulationResult,
    *,
    include_idle: bool = True,
) -> list[str]:
    batch_by_id = schedule_bundle.batches
    machine_name_by_id = {
        machine_id: machine.name or machine_id
        for machine_id, machine in schedule_bundle.machines.items()
    }
    operation_by_id = {
        operation.operation_id: operation
        for operation in schedule_bundle.schedule_operations
    }
    operation_result_by_id = {
        operation.operation_id: operation
        for operation in simulation_result.operations
    }
    step_by_batch_and_step = {
        (batch.batch_id, step.step_id): step
        for batch in schedule_bundle.batches.values()
        for step in batch.route
    }
    availability_time_by_operation: dict[str, float] = {}

    lines: list[str] = []
    for event in simulation_result.events:
        if event.event_type == "operation_available" and event.operation_id is not None:
            availability_time_by_operation[event.operation_id] = event.time
        line = _format_event_line(
            event=event,
            batch_by_id=batch_by_id,
            machine_name_by_id=machine_name_by_id,
            operation_by_id=operation_by_id,
            operation_result_by_id=operation_result_by_id,
            step_by_batch_and_step=step_by_batch_and_step,
            availability_time_by_operation=availability_time_by_operation,
            include_idle=include_idle,
        )
        if line is not None:
            lines.append(line)
    return lines


def write_product_tracker(
    file_path: str | Path,
    schedule_bundle: ScheduleBundle,
    simulation_result: SimulationResult,
    *,
    include_idle: bool = True,
    header_lines: Iterable[str] | None = None,
) -> list[str]:
    lines: list[str] = []
    if header_lines is not None:
        header = [str(line) for line in header_lines]
        if header:
            lines.extend(header)
            lines.append("")

    lines.extend(
        build_product_tracker_lines(
            schedule_bundle=schedule_bundle,
            simulation_result=simulation_result,
            include_idle=include_idle,
        )
    )
    Path(file_path).write_text("\n".join(lines), encoding="utf-8")
    return lines


def _format_event_line(
    *,
    event: EventRecord,
    batch_by_id,
    machine_name_by_id,
    operation_by_id,
    operation_result_by_id,
    step_by_batch_and_step,
    availability_time_by_operation,
    include_idle: bool,
) -> str | None:
    if event.event_type in {"idle_started", "idle_ended"} and not include_idle:
        return None

    prefix = f"{event.time:7.2f} - "
    batch = batch_by_id.get(event.batch_id) if event.batch_id is not None else None
    batch_label = _batch_label(batch)
    machine_name = _machine_name(machine_name_by_id, event.machine_id)
    operation_name = _operation_name(
        event.batch_id,
        event.operation_id,
        operation_by_id,
        batch_by_id,
        step_by_batch_and_step,
    )

    if event.event_type == "batch_released" and batch is not None:
        root_names = ", ".join(
            _operation_name(
                batch.batch_id,
                operation_id,
                operation_by_id,
                batch_by_id,
                step_by_batch_and_step,
            )
            for operation_id in event.details.get("root_operation_ids", [])
        )
        return f"{prefix}{batch_label} RELEASED into the system. Root operations: {root_names}."

    if event.event_type == "operation_available" and batch is not None:
        reason = _AVAILABILITY_REASON_LABELS.get(
            str(event.details.get("reason", "")).strip(),
            str(event.details.get("reason", "unknown")).replace("_", " "),
        )
        return f"{prefix}{batch_label} {operation_name} became AVAILABLE on {machine_name}. Reason: {reason}."

    if event.event_type == "idle_started" and batch is not None:
        reason = _IDLE_REASON_LABELS.get(
            str(event.details.get("idle_reason", "")),
            str(event.details.get("idle_reason", "waiting")).replace("_", " "),
        )
        return f"{prefix}{batch_label} {machine_name} started WAITING before {operation_name}. Reason: {reason}."

    if event.event_type == "idle_ended" and batch is not None:
        reason = _IDLE_REASON_LABELS.get(
            str(event.details.get("idle_reason", "")),
            str(event.details.get("idle_reason", "waiting")).replace("_", " "),
        )
        duration = float(event.details.get("duration", 0.0))
        return (
            f"{prefix}{batch_label} {machine_name} finished WAITING before {operation_name}. "
            f"Reason: {reason}. Idle duration: {duration:.2f} min."
        )

    if event.event_type == "schedule_hold_started" and batch is not None:
        duration = float(event.details.get("duration", 0.0))
        return (
            f"{prefix}{batch_label} {operation_name} is HELD on {machine_name} until its planned schedule window. "
            f"Hold duration: {duration:.2f} min."
        )

    if event.event_type == "setup_started" and batch is not None:
        setup_time = float(event.details.get("setup_time", 0.0))
        return (
            f"{prefix}{batch_label} SETUP STARTED on {machine_name} before {operation_name}. "
            f"Planned setup time: {setup_time:.2f} min."
        )

    if event.event_type == "processing_started" and batch is not None:
        wait_duration = None
        if event.operation_id in availability_time_by_operation:
            wait_duration = event.time - availability_time_by_operation[event.operation_id]
        operation = operation_by_id.get(event.operation_id)
        planned_window = ""
        if operation is not None:
            planned_window = (
                f" Planned window: {operation.planned_start:.2f} -> {operation.planned_end:.2f}."
            )
        wait_text = ""
        if wait_duration is not None:
            wait_text = f" Wait after availability: {wait_duration:.2f} min."
        return f"{prefix}{batch_label} STARTED {operation_name} on {machine_name}.{wait_text}{planned_window}"

    if event.event_type == "processing_completed" and batch is not None:
        operation_result = operation_result_by_id.get(event.operation_id)
        elapsed = None
        active = None
        if operation_result is not None:
            active = operation_result.sampled_process_time
            if operation_result.actual_start is not None and operation_result.actual_end is not None:
                elapsed = operation_result.actual_end - operation_result.actual_start
        details = []
        if elapsed is not None:
            details.append(f"Elapsed on machine: {elapsed:.2f} min")
        if active is not None:
            details.append(f"Active processing time: {active:.2f} min")
        suffix = ""
        if details:
            suffix = " " + ". ".join(details) + "."
        return f"{prefix}{batch_label} COMPLETED {operation_name} on {machine_name}.{suffix}"

    if event.event_type == "shift_pause_started" and batch is not None:
        duration = float(event.details.get("duration", 0.0))
        phase = str(event.details.get("phase", "processing"))
        return (
            f"{prefix}{batch_label} SHIFT PAUSE interrupted {phase} of {operation_name} on {machine_name}. "
            f"Pause duration: {duration:.2f} min."
        )

    if event.event_type == "breakdown_started" and batch is not None:
        phase = str(event.details.get("phase", "processing"))
        return f"{prefix}{batch_label} BREAKDOWN STARTED on {machine_name} during {phase} of {operation_name}."

    if event.event_type == "breakdown_ended" and batch is not None:
        phase = str(event.details.get("phase", "processing"))
        return f"{prefix}{batch_label} BREAKDOWN ENDED on {machine_name}. {operation_name} resumes {phase}."

    if event.event_type == "basket_released":
        product_id = str(event.details.get("product_id", "UNKNOWN"))
        quantity = float(event.details.get("released_quantity", 0.0))
        released_operations = int(event.details.get("released_operations", 0))
        return (
            f"{prefix}{machine_name} basket RELEASED product {product_id}. "
            f"Quantity: {quantity:.2f}. Released operations: {released_operations}."
        )

    if event.event_type == "transfer_started" and batch is not None:
        next_machine_name = _machine_name(machine_name_by_id, event.details.get("next_machine_id"))
        next_operation_name = _operation_name(
            event.batch_id,
            event.details.get("next_operation_id"),
            operation_by_id,
            batch_by_id,
            step_by_batch_and_step,
        )
        travel_time = float(event.details.get("travel_time", 0.0))
        return (
            f"{prefix}{batch_label} TRANSFER STARTED from {machine_name} to {next_machine_name} "
            f"for {next_operation_name}. Travel time: {travel_time:.2f} min."
        )

    if event.event_type == "transfer_completed" and batch is not None:
        predecessor_name = _operation_name(
            event.batch_id,
            event.details.get("predecessor_operation_id"),
            operation_by_id,
            batch_by_id,
            step_by_batch_and_step,
        )
        return (
            f"{prefix}{batch_label} TRANSFER COMPLETED to {machine_name}. "
            f"{operation_name} received input from {predecessor_name}."
        )

    if event.event_type == "batch_completed" and batch is not None:
        return f"{prefix}{batch_label} COMPLETED."

    return None


def _batch_label(batch) -> str:
    if batch is None:
        return "Batch <unknown>"
    family = batch.family_id or batch.product_id
    return f"Batch {batch.batch_id} [{family}]"


def _machine_name(machine_name_by_id, machine_id) -> str:
    if machine_id is None:
        return "Unknown machine"
    return machine_name_by_id.get(str(machine_id), str(machine_id))


def _operation_name(
    batch_id,
    operation_id,
    operation_by_id,
    batch_by_id,
    step_by_batch_and_step,
) -> str:
    if batch_id is None or operation_id is None:
        return str(operation_id or "Unknown operation")
    operation = operation_by_id.get(str(operation_id))
    if operation is None:
        return str(operation_id)
    batch = batch_by_id.get(str(batch_id))
    if batch is None:
        return str(operation.step_id)
    step = step_by_batch_and_step.get((batch.batch_id, operation.step_id))
    if step is None:
        return str(operation.step_id)
    return str(step.name or step.step_id)
