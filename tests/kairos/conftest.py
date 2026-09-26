"""
Shared pytest fixtures for Kairos tests.

All fixtures defined here are automatically available to all test files.
"""

import pytest
import pandas as pd
from typing import List

from kairos import (
    Task, Job, Machine, SchedulingProblem, SolutionResult,
    SolverFactory, SolverType, ObjectiveType
)
from kairos.domain.models import ScheduledTask


# ============================================================
# Basic Model Fixtures
# ============================================================

@pytest.fixture
def machine():
    """Single machine fixture."""
    return Machine(id=1, name="M1")


@pytest.fixture
def fast_machine():
    """Machine with hourly cost."""
    return Machine(id=2, name="Fast_CNC", hourly_cost=100)


@pytest.fixture
def task():
    """Simple task fixture."""
    task = Task(id=1, name="Task1", task_type="Welding", setup_time=25)
    task.add_alternative(1, 100)
    return task


@pytest.fixture
def task_with_alternatives():
    """Task with multiple machine alternatives."""
    task = Task(id=1, name="MultiTask", task_type="Welding")
    task.add_alternative(1, 100)
    task.add_alternative(2, 80)
    return task


@pytest.fixture
def job():
    """Job fixture with due date and priority."""
    return Job(id="J1", name="Product A", due_date=500, priority=2, task_type="Assembly")


# ============================================================
# Problem Fixtures
# ============================================================

@pytest.fixture
def empty_problem():
    """Empty scheduling problem."""
    return SchedulingProblem(name="Empty")


@pytest.fixture
def simple_problem():
    """Simple problem with 1 machine and 1 task."""
    problem = SchedulingProblem(name="Simple")
    problem.add_machine(Machine(id=1, name="M1"))
    
    task = Task(id=1, name="T1")
    task.add_alternative(1, 100)
    problem.add_task(task)
    
    return problem


@pytest.fixture
def multi_machine_problem():
    """Problem with 2 machines and flexible task."""
    problem = SchedulingProblem(name="MultiMachine")
    problem.add_machine(Machine(id=1, name="M1"))
    problem.add_machine(Machine(id=2, name="M2"))
    
    task = Task(id=1, name="Flexible")
    task.add_alternative(1, 100)
    task.add_alternative(2, 80)
    problem.add_task(task)
    
    return problem


@pytest.fixture
def precedence_problem():
    """Problem with precedence constraints."""
    problem = SchedulingProblem(name="Precedence")
    problem.add_machine(Machine(id=1, name="M1"))
    problem.add_machine(Machine(id=2, name="M2"))
    
    t1 = Task(id=1, name="T1", task_type="A")
    t1.add_alternative(1, 50)
    t1.add_alternative(2, 40)
    
    t2 = Task(id=2, name="T2", task_type="B", setup_time=10)
    t2.add_alternative(1, 60)
    t2.add_predecessor(t1)
    
    problem.add_task(t1)
    problem.add_task(t2)
    
    return problem


@pytest.fixture
def job_problem():
    """Problem with jobs containing tasks."""
    problem = SchedulingProblem(name="JobProblem")
    problem.add_machine(Machine(id=1, name="M1"))
    
    job = Job(id="J1", name="Product", due_date=200, priority=2)
    
    t1 = Task(id=1, name="Weld", task_type="Welding", setup_time=25)
    t1.add_alternative(1, 50)
    
    t2 = Task(id=2, name="Paint", task_type="Painting", setup_time=15)
    t2.add_alternative(1, 30)
    t2.add_predecessor(t1)
    
    job.add_task(t1)
    job.add_task(t2)
    problem.add_job(job)
    
    return problem


@pytest.fixture
def large_problem():
    """Larger problem for performance testing."""
    problem = SchedulingProblem(name="Large")
    problem.add_machine(Machine(id=1, name="M1"))
    
    for i in range(15):
        task = Task(id=i, name=f"T{i}", task_type=f"Type{i % 3}", setup_time=5)
        task.add_alternative(1, 10)
        problem.add_task(task)
    
    return problem


# ============================================================
# Solver Fixtures
# ============================================================

@pytest.fixture
def cpsat_solver():
    """CP-SAT solver with default settings."""
    return SolverFactory.get_solver(SolverType.CP_SAT)


@pytest.fixture
def logging_solver():
    """CP-SAT solver with logging enabled."""
    return SolverFactory.get_solver(SolverType.CP_SAT, logging_enabled=True)


@pytest.fixture
def tardiness_solver():
    """CP-SAT solver with weighted tardiness objective."""
    return SolverFactory.get_solver(
        SolverType.CP_SAT,
        objective_type=ObjectiveType.WEIGHTED_TARDINESS
    )


# ============================================================
# Result Fixtures
# ============================================================

@pytest.fixture
def sample_result():
    """Sample successful solution result."""
    task1 = Task(id=1, name="Task1", task_type="Welding")
    task2 = Task(id=2, name="Task2", task_type="Painting")
    machine = Machine(id=1, name="M1")
    
    job = Job(id="J1", name="Job1", due_date=200)
    job.add_task(task1)
    job.add_task(task2)
    
    schedule = [
        ScheduledTask(task=task1, machine=machine, start_time=0, end_time=50, duration=50),
        ScheduledTask(task=task2, machine=machine, start_time=60, end_time=100, duration=40),
    ]
    
    result = SolutionResult(status="OPTIMAL", schedule=schedule)
    result.calculate_metrics([job])
    return result


@pytest.fixture
def empty_result():
    """Empty/failed solution result."""
    return SolutionResult(status="INFEASIBLE", schedule=[])


# ============================================================
# Excel Test Fixtures
# ============================================================

@pytest.fixture
def simple_excel_file(tmp_path):
    """Create a simple Excel file for testing."""
    file_path = tmp_path / "test_schedule.xlsx"
    
    machines_df = pd.DataFrame({
        "id": [1, 2],
        "name": ["M1", "M2"],
        "hourly_cost": [50.0, 100.0]
    })
    
    tasks_df = pd.DataFrame({
        "id": [101, 102],
        "name": ["Task_A", "Task_B"],
        "task_type": ["Welding", "Painting"],
        "setup_time": [25, 15],
        "alternatives": ["1:100,2:80", "1:50"],
        "predecessors": ["", "101"]
    })
    
    with pd.ExcelWriter(file_path) as writer:
        machines_df.to_excel(writer, sheet_name="Machines", index=False)
        tasks_df.to_excel(writer, sheet_name="Tasks", index=False)
    
    return str(file_path)


@pytest.fixture
def excel_with_jobs(tmp_path):
    """Create Excel file with Jobs sheet."""
    file_path = tmp_path / "test_jobs.xlsx"
    
    machines_df = pd.DataFrame({"id": [1], "name": ["M1"]})
    
    jobs_df = pd.DataFrame({
        "id": ["JOB_1", "JOB_2"],
        "name": ["Product A", "Product B"],
        "due_date": [500, 600],
        "priority": [2, 1],
        "task_type": ["Assembly", "Welding"]
    })
    
    tasks_df = pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["T1", "T2", "T3"],
        "job_id": ["JOB_1", "JOB_1", "JOB_2"],
        "task_type": ["", "", ""],
        "setup_time": [10, 10, 20],
        "alternatives": ["1:50", "1:60", "1:40"],
        "predecessors": ["", "1", ""]
    })
    
    with pd.ExcelWriter(file_path) as writer:
        machines_df.to_excel(writer, sheet_name="Machines", index=False)
        jobs_df.to_excel(writer, sheet_name="Jobs", index=False)
        tasks_df.to_excel(writer, sheet_name="Tasks", index=False)
    
    return str(file_path)


# ============================================================
# Heuristic Solver Fixtures
# ============================================================

@pytest.fixture
def uniform_single_machine_problem():
    """Single machine, uniform durations for heuristic tests."""
    problem = SchedulingProblem(name="SingleMachine")
    problem.add_machine(Machine(id=1, name="M1"))
    
    for i in range(3):
        task = Task(id=i, name=f"T{i}")
        task.add_alternative(1, 10 * (i + 1))  # 10, 20, 30
        problem.add_task(task)
    
    return problem


@pytest.fixture
def uniform_parallel_machines_problem():
    """Parallel machines, same duration on all (identical parallel machines)."""
    problem = SchedulingProblem(name="ParallelMachines")
    problem.add_machine(Machine(id=1, name="M1"))
    problem.add_machine(Machine(id=2, name="M2"))
    
    for i in range(4):
        task = Task(id=i, name=f"T{i}")
        task.add_alternative(1, 20)  # Same duration on both
        task.add_alternative(2, 20)
        problem.add_task(task)
    
    return problem


@pytest.fixture
def variable_speed_problem():
    """Problem with different durations on machines (VARIABLE_SPEED/unrelated machines)."""
    problem = SchedulingProblem(name="VariableSpeed")
    problem.add_machine(Machine(id=1, name="M1"))
    problem.add_machine(Machine(id=2, name="M2"))
    
    task = Task(id=1, name="T1")
    task.add_alternative(1, 100)  # Different durations!
    task.add_alternative(2, 80)
    problem.add_task(task)
    
    return problem


@pytest.fixture
def setup_times_problem():
    """Problem with setup times (sequence-dependent)."""
    problem = SchedulingProblem(name="SetupTimes")
    problem.add_machine(Machine(id=1, name="M1"))
    
    task = Task(id=1, name="T1", task_type="A", setup_time=15)
    task.add_alternative(1, 50)
    problem.add_task(task)
    
    return problem


@pytest.fixture
def problem_with_due_dates():
    """Problem with jobs having due dates for EDD tests."""
    problem = SchedulingProblem(name="DueDates")
    problem.add_machine(Machine(id=1, name="M1"))
    
    job1 = Job(id="J1", name="Job1", due_date=100, priority=2)
    job2 = Job(id="J2", name="Job2", due_date=50, priority=1)
    
    t1 = Task(id=1, name="T1")
    t1.add_alternative(1, 30)
    job1.add_task(t1)
    
    t2 = Task(id=2, name="T2")
    t2.add_alternative(1, 40)
    job2.add_task(t2)
    
    problem.add_job(job1)
    problem.add_job(job2)
    
    return problem


@pytest.fixture
def simple_precedence_problem():
    """Simple single-machine precedence problem for heuristic rejection tests."""
    problem = SchedulingProblem(name="SimplePrecedence")
    problem.add_machine(Machine(id=1, name="M1"))
    
    t1 = Task(id=1, name="T1")
    t1.add_alternative(1, 50)
    
    t2 = Task(id=2, name="T2")
    t2.add_alternative(1, 30)
    t2.add_predecessor(t1)
    
    problem.add_task(t1)
    problem.add_task(t2)
    
    return problem


# ============================================================
# SRPT Preemption Fixtures
# ============================================================

@pytest.fixture
def preemption_single_machine():
    """Single machine problem with preemption enabled."""
    problem = SchedulingProblem(name="PreemptionSingle")
    problem.enable_preemption()
    problem.add_machine(Machine(id=1, name="M1"))
    
    t1 = Task(id=1, name="Long", release_time=0)
    t1.add_alternative(1, 100)
    
    t2 = Task(id=2, name="Short", release_time=10)
    t2.add_alternative(1, 20)
    
    problem.add_task(t1)
    problem.add_task(t2)
    
    return problem


@pytest.fixture
def preemption_multi_machine():
    """Multi-machine problem with preemption enabled."""
    problem = SchedulingProblem(name="PreemptionMulti")
    problem.enable_preemption()
    problem.add_machine(Machine(id=1, name="M1"))
    problem.add_machine(Machine(id=2, name="M2"))
    
    t1 = Task(id=1, name="T1", release_time=0)
    t1.add_alternative(1, 100)
    t1.add_alternative(2, 100)
    
    t2 = Task(id=2, name="T2", release_time=0)
    t2.add_alternative(1, 50)
    t2.add_alternative(2, 50)
    
    t3 = Task(id=3, name="T3", release_time=20)
    t3.add_alternative(1, 10)
    t3.add_alternative(2, 10)
    
    problem.add_task(t1)
    problem.add_task(t2)
    problem.add_task(t3)
    
    return problem


@pytest.fixture
def no_preemption_problem():
    """Problem without preemption enabled for rejection test."""
    problem = SchedulingProblem(name="NoPreemption")
    problem.add_machine(Machine(id=1, name="M1"))
    
    task = Task(id=1, name="T1")
    task.add_alternative(1, 50)
    problem.add_task(task)
    
    return problem
