from __future__ import annotations

from collections import defaultdict

from .models import Batch, EPSILON, RouteStep, ScheduleBundle, ScheduleOperation


class ValidationError(ValueError):
    pass


def validate_schedule_bundle(bundle: ScheduleBundle) -> None:
    _validate_machines(bundle)
    _validate_batches(bundle)
    _validate_schedule_references(bundle)
    _validate_basket_rules(bundle)
    _validate_travel(bundle)
    _validate_basket_segments(bundle)


def _validate_machines(bundle: ScheduleBundle) -> None:
    for machine in bundle.machines.values():
        for window in machine.calendar.working_windows:
            if window.start < 0 or window.end - EPSILON > bundle.week_horizon:
                raise ValidationError(
                    f"Calendar window {window!r} for machine {machine.machine_id!r} exceeds the weekly horizon."
                )


def _validate_batches(bundle: ScheduleBundle) -> None:
    for batch in bundle.batches.values():
        if batch.release_time - EPSILON > bundle.week_horizon:
            raise ValidationError(f"Batch {batch.batch_id!r} releases after the weekly horizon.")
        ordered_steps = _ordered_batch_steps(batch)
        step_sequences = [step.sequence for step in ordered_steps]
        if step_sequences != sorted(step_sequences):
            raise ValidationError(f"Batch {batch.batch_id!r} route steps must be sorted by sequence.")
        step_lookup = {step.step_id: step for step in ordered_steps}
        predecessor_map = resolve_step_predecessors(batch)
        for step in ordered_steps:
            for predecessor_step_id in predecessor_map[step.step_id]:
                predecessor = step_lookup.get(predecessor_step_id)
                if predecessor is None:
                    raise ValidationError(
                        f"Batch {batch.batch_id!r} step {step.step_id!r} references unknown predecessor {predecessor_step_id!r}."
                    )
                if predecessor.sequence >= step.sequence:
                    raise ValidationError(
                        f"Batch {batch.batch_id!r} step {step.step_id!r} must have predecessors with lower sequence numbers."
                    )


def _validate_schedule_references(bundle: ScheduleBundle) -> None:
    operation_ids: set[str] = set()
    operations_by_machine: dict[str, list[ScheduleOperation]] = defaultdict(list)
    operations_by_batch: dict[str, list[ScheduleOperation]] = defaultdict(list)
    for operation in bundle.schedule_operations:
        if operation.operation_id in operation_ids:
            raise ValidationError(f"Duplicate operation id {operation.operation_id!r}.")
        operation_ids.add(operation.operation_id)
        if operation.machine_id not in bundle.machines:
            raise ValidationError(f"Operation {operation.operation_id!r} references unknown machine {operation.machine_id!r}.")
        if operation.batch_id not in bundle.batches:
            raise ValidationError(f"Operation {operation.operation_id!r} references unknown batch {operation.batch_id!r}.")
        batch = bundle.batches[operation.batch_id]
        route_steps = {step.step_id for step in batch.route}
        if operation.step_id not in route_steps:
            raise ValidationError(
                f"Operation {operation.operation_id!r} references unknown step {operation.step_id!r} for batch {batch.batch_id!r}."
            )
        operations_by_machine[operation.machine_id].append(operation)
        operations_by_batch[operation.batch_id].append(operation)
        if operation.planned_start < 0 or operation.planned_end - EPSILON > bundle.week_horizon:
            raise ValidationError(f"Operation {operation.operation_id!r} lies outside the weekly horizon.")

    for machine_id, operations in operations_by_machine.items():
        sequences = [operation.machine_sequence for operation in operations]
        if len(sequences) != len(set(sequences)):
            raise ValidationError(f"Machine {machine_id!r} has duplicate machine_sequence values.")

    for batch_id, batch in bundle.batches.items():
        operations = operations_by_batch.get(batch_id, [])
        if len(operations) != len(batch.route):
            raise ValidationError(
                f"Batch {batch_id!r} has {len(batch.route)} route steps but {len(operations)} scheduled operations."
            )
        scheduled_step_ids = {operation.step_id for operation in operations}
        route_step_ids = {step.step_id for step in batch.route}
        if scheduled_step_ids != route_step_ids:
            raise ValidationError(f"Batch {batch_id!r} schedule steps do not match its route definition.")


def _validate_basket_rules(bundle: ScheduleBundle) -> None:
    for batch in bundle.batches.values():
        for operation in (item for item in bundle.schedule_operations if item.batch_id == batch.batch_id):
            rule_key = (operation.machine_id, batch.product_id)
            if rule_key not in bundle.basket_rules:
                raise ValidationError(
                    f"Missing basket rule for machine {operation.machine_id!r} and product {batch.product_id!r}."
                )


def _validate_travel(bundle: ScheduleBundle) -> None:
    operations_by_batch: dict[str, list[ScheduleOperation]] = defaultdict(list)
    for operation in bundle.schedule_operations:
        operations_by_batch[operation.batch_id].append(operation)
    for batch_id, operations in operations_by_batch.items():
        batch = bundle.batches[batch_id]
        operation_by_step = {operation.step_id: operation for operation in operations}
        predecessor_map = resolve_step_predecessors(batch)
        for step in batch.route:
            current_operation = operation_by_step[step.step_id]
            for predecessor_step_id in predecessor_map[step.step_id]:
                predecessor_operation = operation_by_step[predecessor_step_id]
                if not bundle.travel_matrix.has_duration(predecessor_operation.machine_id, current_operation.machine_id):
                    raise ValidationError(
                        "Missing travel duration for "
                        f"{predecessor_operation.machine_id!r} -> {current_operation.machine_id!r} "
                        f"in batch {batch_id!r} ({predecessor_step_id!r} -> {step.step_id!r})."
                    )


def _validate_basket_segments(bundle: ScheduleBundle) -> None:
    operations_by_machine: dict[str, list[ScheduleOperation]] = defaultdict(list)
    for operation in bundle.schedule_operations:
        operations_by_machine[operation.machine_id].append(operation)

    for machine_id, operations in operations_by_machine.items():
        ordered = sorted(operations, key=lambda operation: operation.machine_sequence)
        current_product: str | None = None
        cumulative_quantity = 0.0
        basket_capacity = 0.0
        for index, operation in enumerate(ordered):
            batch = bundle.batches[operation.batch_id]
            product_id = batch.product_id
            if current_product is None or product_id != current_product:
                if current_product is not None and cumulative_quantity > EPSILON:
                    raise ValidationError(
                        f"Machine {machine_id!r} changes away from product {current_product!r} before its basket empties."
                    )
                current_product = product_id
                basket_capacity = bundle.basket_rules[(machine_id, product_id)].capacity_quantity
                cumulative_quantity = 0.0

            cumulative_quantity += batch.quantity
            if cumulative_quantity + EPSILON >= basket_capacity:
                cumulative_quantity = 0.0

            is_last_operation = index == len(ordered) - 1
            if is_last_operation:
                break


def group_operations_by_batch(bundle: ScheduleBundle) -> dict[str, list[ScheduleOperation]]:
    operations_by_batch: dict[str, list[ScheduleOperation]] = defaultdict(list)
    for operation in bundle.schedule_operations:
        operations_by_batch[operation.batch_id].append(operation)
    for batch_id, operations in operations_by_batch.items():
        batch: Batch = bundle.batches[batch_id]
        order_lookup = {step.step_id: step.sequence for step in _ordered_batch_steps(batch)}
        operations.sort(key=lambda operation: order_lookup[operation.step_id])
    return operations_by_batch


def _ordered_batch_steps(batch: Batch) -> list[RouteStep]:
    return sorted(batch.route, key=lambda step: (step.sequence, step.step_id))


def resolve_step_predecessors(batch: Batch) -> dict[str, tuple[str, ...]]:
    ordered_steps = _ordered_batch_steps(batch)
    resolved: dict[str, tuple[str, ...]] = {}
    for index, step in enumerate(ordered_steps):
        if step.predecessor_step_ids is None:
            resolved[step.step_id] = (ordered_steps[index - 1].step_id,) if index > 0 else ()
        else:
            resolved[step.step_id] = step.predecessor_step_ids
    return resolved
