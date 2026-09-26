import pytest

pytest.importorskip("ortools")

from src.validation.jsplib_parser import read_jsplib_standard
from src.validation.jsplib_runner import solve_jsplib_makespan
from src.validation.schedule_checker import check_schedule_feasibility


def test_ft06_solves_to_known_optimum() -> None:
    jobs_data, _n_jobs, n_machines = read_jsplib_standard("benchmarks/jsplib/ft06.txt")

    result = solve_jsplib_makespan(jobs_data, n_machines, time_limit_seconds=60)
    feasibility_errors = check_schedule_feasibility(result.schedule, jobs_data, n_machines)

    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert feasibility_errors == []
    assert result.makespan == 55
