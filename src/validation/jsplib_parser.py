"""Parser for standard JSPLIB job-shop benchmark instances."""

from __future__ import annotations

from pathlib import Path

OperationData = tuple[int, int]
JobsData = list[list[OperationData]]


def read_jsplib_standard(path: str) -> tuple[JobsData, int, int]:
    """Read a standard JSPLIB instance with fixed machine-duration routing."""
    instance_path = Path(path)
    lines = [
        line.strip()
        for line in instance_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise ValueError(f"JSPLIB instance is empty: {path}")

    header = _parse_ints(lines[0], line_number=1)
    if len(header) != 2:
        raise ValueError("JSPLIB header must contain exactly two integers: jobs machines")

    n_jobs, n_machines = header
    if n_jobs <= 0 or n_machines <= 0:
        raise ValueError("Number of jobs and machines must be positive")
    if len(lines) - 1 != n_jobs:
        raise ValueError(f"Expected {n_jobs} job rows, found {len(lines) - 1}")

    jobs_data: JobsData = []
    expected_values = 2 * n_machines
    for job_index, line in enumerate(lines[1:], start=0):
        values = _parse_ints(line, line_number=job_index + 2)
        if len(values) != expected_values:
            raise ValueError(
                f"Job row {job_index} must contain {expected_values} integers, "
                f"found {len(values)}"
            )

        operations: list[OperationData] = []
        for pair_index in range(0, len(values), 2):
            machine_id = values[pair_index]
            processing_time = values[pair_index + 1]
            if machine_id < 0 or machine_id >= n_machines:
                raise ValueError(
                    f"Job {job_index} uses invalid machine {machine_id}; "
                    f"expected 0..{n_machines - 1}"
                )
            if processing_time <= 0:
                raise ValueError(
                    f"Job {job_index}, operation {pair_index // 2} has non-positive "
                    f"processing time {processing_time}"
                )
            operations.append((machine_id, processing_time))
        jobs_data.append(operations)

    return jobs_data, n_jobs, n_machines


def _parse_ints(line: str, line_number: int) -> list[int]:
    try:
        return [int(value) for value in line.split()]
    except ValueError as exc:
        raise ValueError(f"Line {line_number} contains a non-integer value") from exc
