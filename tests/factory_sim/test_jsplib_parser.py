from pathlib import Path

from src.validation.jsplib_parser import read_jsplib_standard


def test_read_ft06_standard_instance() -> None:
    instance_path = Path("benchmarks/jsplib/ft06.txt")

    jobs_data, n_jobs, n_machines = read_jsplib_standard(str(instance_path))

    assert n_jobs == 6
    assert n_machines == 6
    assert len(jobs_data) == 6
    assert all(len(job) == 6 for job in jobs_data)
    assert jobs_data[0] == [(2, 1), (0, 3), (1, 6), (3, 7), (5, 3), (4, 6)]
