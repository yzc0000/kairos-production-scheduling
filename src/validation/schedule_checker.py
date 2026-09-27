"""Feasibility checks for JSPLIB schedules."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from src.validation.jsplib_parser import JobsData

ScheduleRow = Mapping[str, int]


def check_schedule_feasibility(
    schedule: Iterable[ScheduleRow],
    jobs_data: JobsData,
    n_machines: int,
) -> list[str]:
    """Return human-readable feasibility errors, or an empty list when valid."""
    errors: list[str] = []
    rows_by_operation: dict[tuple[int, int], list[ScheduleRow]] = defaultdict(list)
    rows_by_machine: dict[int, list[ScheduleRow]] = defaultdict(list)
    expected_operations = {
        (job_id, operation_id)
        for job_id, job in enumerate(jobs_data)
        for operation_id, _operation in enumerate(job)
    }

    for index, row in enumerate(schedule):
        missing_keys = {
            key
            for key in (
                "job_id",
                "operation_id",
                "machine_id",
                "processing_time",
                "start",
                "end",
            )
            if key not in row
        }
        if missing_keys:
            errors.append(f"Schedule row {index} is missing keys: {sorted(missing_keys)}")
            continue

        job_id = row["job_id"]
        operation_id = row["operation_id"]
        machine_id = row["machine_id"]
        processing_time = row["processing_time"]
        start = row["start"]
        end = row["end"]

        operation_key = (job_id, operation_id)
        rows_by_operation[operation_key].append(row)

        if operation_key not in expected_operations:
            errors.append(f"Unexpected operation in schedule: job {job_id}, op {operation_id}")
            continue

        expected_machine, expected_duration = jobs_data[job_id][operation_id]
        if end - start != processing_time:
            errors.append(
                f"Job {job_id}, op {operation_id} has end-start={end - start}, "
                f"but processing_time={processing_time}"
            )
        if processing_time != expected_duration:
            errors.append(
                f"Job {job_id}, op {operation_id} has processing_time={processing_time}, "
                f"expected {expected_duration}"
            )
        if machine_id != expected_machine:
            errors.append(
                f"Job {job_id}, op {operation_id} assigned to machine {machine_id}, "
                f"expected {expected_machine}"
            )
        if machine_id < 0 or machine_id >= n_machines:
            errors.append(f"Job {job_id}, op {operation_id} uses invalid machine {machine_id}")
        if start < 0 or end < 0:
            errors.append(f"Job {job_id}, op {operation_id} has negative start/end")
        if end < start:
            errors.append(f"Job {job_id}, op {operation_id} ends before it starts")

        rows_by_machine[machine_id].append(row)

    _check_completeness(errors, expected_operations, rows_by_operation)
    _check_precedence(errors, jobs_data, rows_by_operation)
    _check_machine_overlap(errors, rows_by_machine)
    return errors


def _check_completeness(
    errors: list[str],
    expected_operations: set[tuple[int, int]],
    rows_by_operation: dict[tuple[int, int], list[ScheduleRow]],
) -> None:
    for operation_key in sorted(expected_operations):
        count = len(rows_by_operation.get(operation_key, []))
        if count == 0:
            errors.append(f"Missing operation in schedule: job {operation_key[0]}, op {operation_key[1]}")
        elif count > 1:
            errors.append(
                f"Duplicate operation in schedule: job {operation_key[0]}, "
                f"op {operation_key[1]} appears {count} times"
            )


def _check_precedence(
    errors: list[str],
    jobs_data: JobsData,
    rows_by_operation: dict[tuple[int, int], list[ScheduleRow]],
) -> None:
    for job_id, job in enumerate(jobs_data):
        for operation_id in range(len(job) - 1):
            current = rows_by_operation.get((job_id, operation_id), [])
            following = rows_by_operation.get((job_id, operation_id + 1), [])
            if len(current) != 1 or len(following) != 1:
                continue
            if current[0]["end"] > following[0]["start"]:
                errors.append(
                    f"Job {job_id} precedence violation: op {operation_id} ends at "
                    f"{current[0]['end']}, op {operation_id + 1} starts at {following[0]['start']}"
                )


def _check_machine_overlap(
    errors: list[str],
    rows_by_machine: dict[int, list[ScheduleRow]],
) -> None:
    for machine_id, machine_rows in rows_by_machine.items():
        ordered_rows = sorted(machine_rows, key=lambda row: (row["start"], row["end"]))
        for left, right in zip(ordered_rows, ordered_rows[1:]):
            if left["end"] > right["start"]:
                errors.append(
                    f"Machine {machine_id} overlap: job {left['job_id']}, op "
                    f"{left['operation_id']} [{left['start']}, {left['end']}) overlaps "
                    f"job {right['job_id']}, op {right['operation_id']} "
                    f"[{right['start']}, {right['end']})"
                )
