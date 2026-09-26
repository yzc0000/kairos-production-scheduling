from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = PROJECT_ROOT / "Kairos-Scheduler-main"

for path in (PROJECT_ROOT, KAIROS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def weighted_tardiness(sequence: list[tuple[str, int, int, int]]) -> int:
    time = 0
    total = 0
    for _job_id, processing_time, due_date, weight in sequence:
        time += processing_time
        total += max(0, time - due_date) * weight
    return total


def test_manual_weighted_tardiness_sequences() -> None:
    job_a = ("A", 4, 5, 10)
    job_b = ("B", 3, 4, 1)

    assert weighted_tardiness([job_a, job_b]) == 3
    assert weighted_tardiness([job_b, job_a]) == 20


def test_kairos_weighted_tardiness_objective_chooses_a_before_b() -> None:
    pytest.importorskip("ortools")
    import kairos as kr

    problem = kr.SchedulingProblem(name="Manual Weighted Tardiness Test")
    problem.add_machine(kr.Machine(id="M1", name="Single Machine"))

    job_a = kr.Job(id="A", name="Job A", due_date=5, priority=10, task_type="A")
    task_a = kr.Task(id="A-op", name="A Operation", task_type="A")
    task_a.add_alternative("M1", 4)
    job_a.add_task(task_a)

    job_b = kr.Job(id="B", name="Job B", due_date=4, priority=1, task_type="B")
    task_b = kr.Task(id="B-op", name="B Operation", task_type="B")
    task_b.add_alternative("M1", 3)
    job_b.add_task(task_b)

    problem.add_job(job_a)
    problem.add_job(job_b)

    solver = kr.SolverFactory.get_solver(
        kr.SolverType.CP_SAT,
        objective_type=kr.ObjectiveType.WEIGHTED_TARDINESS,
    )
    result = solver.solve(problem, time_limit_seconds=30)
    starts_by_job = {scheduled.job_id: scheduled.start_time for scheduled in result.schedule}

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.weighted_tardiness == 3
    assert result.objective_value == 3
    assert starts_by_job["A"] < starts_by_job["B"]
