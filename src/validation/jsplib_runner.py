"""CLI and CP-SAT solver for JSPLIB makespan validation."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

from ortools.sat.python import cp_model

from src.validation.jsplib_parser import JobsData, read_jsplib_standard
from src.validation.schedule_checker import check_schedule_feasibility

FT06_EXPECTED_MAKESPAN = 55


@dataclass(frozen=True)
class JSPLIBScheduleRow:
    job_id: int
    operation_id: int
    machine_id: int
    processing_time: int
    start: int
    end: int

    def to_dict(self) -> dict[str, int]:
        return {
            "job_id": self.job_id,
            "operation_id": self.operation_id,
            "machine_id": self.machine_id,
            "processing_time": self.processing_time,
            "start": self.start,
            "end": self.end,
        }


@dataclass
class JSPLIBSolveResult:
    status: str
    makespan: int | None = None
    schedule: list[dict[str, int]] = field(default_factory=list)
    runtime_seconds: float = 0.0


def solve_jsplib_makespan(
    jobs_data: JobsData,
    n_machines: int,
    time_limit_seconds: int = 60,
) -> JSPLIBSolveResult:
    """Solve a fixed-route JSPLIB instance with makespan minimization."""
    start_time = time.time()
    model = cp_model.CpModel()
    horizon = sum(duration for job in jobs_data for _machine, duration in job)

    starts: dict[tuple[int, int], cp_model.IntVar] = {}
    ends: dict[tuple[int, int], cp_model.IntVar] = {}
    machine_intervals: dict[int, list[cp_model.IntervalVar]] = {
        machine_id: [] for machine_id in range(n_machines)
    }

    for job_id, job in enumerate(jobs_data):
        for operation_id, (machine_id, processing_time) in enumerate(job):
            suffix = f"j{job_id}_o{operation_id}_m{machine_id}"
            start = model.NewIntVar(0, horizon, f"start_{suffix}")
            end = model.NewIntVar(0, horizon, f"end_{suffix}")
            interval = model.NewIntervalVar(start, processing_time, end, f"interval_{suffix}")
            starts[(job_id, operation_id)] = start
            ends[(job_id, operation_id)] = end
            machine_intervals[machine_id].append(interval)

    for job_id, job in enumerate(jobs_data):
        for operation_id in range(len(job) - 1):
            model.Add(ends[(job_id, operation_id)] <= starts[(job_id, operation_id + 1)])

    for intervals in machine_intervals.values():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)

    makespan = model.NewIntVar(0, horizon, "makespan")
    final_operation_ends = [ends[(job_id, len(job) - 1)] for job_id, job in enumerate(jobs_data)]
    model.AddMaxEquality(makespan, final_operation_ends)
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 8

    status_code = solver.Solve(model)
    runtime_seconds = time.time() - start_time
    status = solver.StatusName(status_code)

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return JSPLIBSolveResult(status=status, runtime_seconds=runtime_seconds)

    schedule_rows = []
    for job_id, job in enumerate(jobs_data):
        for operation_id, (machine_id, processing_time) in enumerate(job):
            row = JSPLIBScheduleRow(
                job_id=job_id,
                operation_id=operation_id,
                machine_id=machine_id,
                processing_time=processing_time,
                start=solver.Value(starts[(job_id, operation_id)]),
                end=solver.Value(ends[(job_id, operation_id)]),
            )
            schedule_rows.append(row.to_dict())

    schedule_rows.sort(key=lambda row: (row["machine_id"], row["start"], row["job_id"]))
    return JSPLIBSolveResult(
        status=status,
        makespan=solver.Value(makespan),
        schedule=schedule_rows,
        runtime_seconds=runtime_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a JSPLIB job-shop instance.")
    parser.add_argument("instance_path", help="Path to a standard JSPLIB instance file")
    parser.add_argument("--time-limit", type=int, default=60, help="CP-SAT time limit in seconds")
    args = parser.parse_args(argv)

    instance_path = Path(args.instance_path)
    jobs_data, n_jobs, n_machines = read_jsplib_standard(str(instance_path))
    result = solve_jsplib_makespan(jobs_data, n_machines, args.time_limit)
    feasibility_errors = check_schedule_feasibility(result.schedule, jobs_data, n_machines)
    feasibility_passed = not feasibility_errors
    optimum_passed = _known_optimum_passed(instance_path, result.makespan)

    print(f"Instance path: {instance_path}")
    print(f"Number of jobs: {n_jobs}")
    print(f"Number of machines: {n_machines}")
    print(f"Solver status: {result.status}")
    print(f"Makespan: {result.makespan}")
    print(f"Schedule feasibility passed: {feasibility_passed}")
    if feasibility_errors:
        print("Feasibility errors:")
        for error in feasibility_errors:
            print(f"  - {error}")
    if instance_path.name.lower() == "ft06.txt":
        print(f"ft06 expected makespan: {FT06_EXPECTED_MAKESPAN}")
        print(f"ft06 optimum check passed: {optimum_passed}")
    print(f"Solver runtime seconds: {result.runtime_seconds:.3f}")

    return 0 if feasibility_passed and optimum_passed else 1


def _known_optimum_passed(instance_path: Path, makespan: int | None) -> bool:
    if instance_path.name.lower() != "ft06.txt":
        return True
    return makespan == FT06_EXPECTED_MAKESPAN


if __name__ == "__main__":
    raise SystemExit(main())
