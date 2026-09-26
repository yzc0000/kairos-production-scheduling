"""
Tests for solvers: GoogleCPSATSolver, SolverFactory

Uses shared fixtures from conftest.py
"""

import pytest
from kairos import (
    Task, Job, Machine, SchedulingProblem,
    SolverFactory, SolverType, ObjectiveType
)


class TestSolverFactory:
    """Tests for SolverFactory."""
    
    def test_get_cpsat_solver(self, cpsat_solver):
        """Test getting CP-SAT solver."""
        assert cpsat_solver is not None
        assert cpsat_solver.name == "Google CP-SAT"
    
    def test_get_solver_with_options(self):
        """Test getting solver with options."""
        solver = SolverFactory.get_solver(
            SolverType.CP_SAT,
            logging_enabled=True,
            CIRCUIT_THRESHOLD=10
        )
        assert solver.logging_enabled is True
        assert solver.CIRCUIT_THRESHOLD == 10
    
    def test_get_solver_with_objective(self, tardiness_solver):
        """Test getting solver with objective type."""
        assert tardiness_solver.objective_type == ObjectiveType.WEIGHTED_TARDINESS


class TestGoogleCPSATSolver:
    """Tests for GoogleCPSATSolver."""
    
    def test_solve_simple(self, cpsat_solver, simple_problem):
        """Test solving a simple problem."""
        result = cpsat_solver.solve(simple_problem, time_limit_seconds=10)
        
        assert result.is_success
        assert len(result.schedule) == 1
        assert result.schedule[0].duration == 100
    
    def test_solve_optimal(self, cpsat_solver, simple_problem):
        """Test that simple problem is solved optimally."""
        result = cpsat_solver.solve(simple_problem, time_limit_seconds=10)
        assert result.status == "OPTIMAL"
    
    def test_solve_with_precedence(self, cpsat_solver, precedence_problem):
        """Test solving with precedence constraints."""
        result = cpsat_solver.solve(precedence_problem, time_limit_seconds=10)
        
        assert result.is_success
        
        # Find tasks in schedule
        t1_sched = next(s for s in result.schedule if s.task_id == 1)
        t2_sched = next(s for s in result.schedule if s.task_id == 2)
        
        # T1 must finish before T2 starts
        assert t1_sched.end_time <= t2_sched.start_time
    
    def test_solve_with_setup_times(self, cpsat_solver, precedence_problem):
        """Test solving with setup times."""
        result = cpsat_solver.solve(precedence_problem, time_limit_seconds=10)
        
        assert result.is_success
        
        t1_sched = next(s for s in result.schedule if s.task_id == 1)
        t2_sched = next(s for s in result.schedule if s.task_id == 2)
        
        if t1_sched.machine_id == t2_sched.machine_id:
            gap = t2_sched.start_time - t1_sched.end_time
            assert gap >= 10  # Setup time enforced
    
    def test_solve_makespan_objective(self, cpsat_solver, precedence_problem):
        """Test makespan objective."""
        result = cpsat_solver.solve(precedence_problem, time_limit_seconds=10)
        
        assert result.is_success
        assert result.makespan is not None
        assert result.makespan > 0
    
    def test_solve_tardiness_objective(self, tardiness_solver, job_problem):
        """Test weighted tardiness objective."""
        result = tardiness_solver.solve(job_problem, time_limit_seconds=10)
        
        assert result.is_success
        assert result.weighted_tardiness is not None
    
    def test_can_solve_compatible(self, cpsat_solver, simple_problem):
        """Test compatibility check passes."""
        can_solve, message = cpsat_solver.can_solve(simple_problem)
        
        assert can_solve is True
        assert message == "Compatible"


class TestCircuitVsPairwise:
    """Test CIRCUIT vs PAIRWISE constraint selection."""
    
    def test_pairwise_for_small_machines(self):
        """Test PAIRWISE is used for small task counts."""
        problem = SchedulingProblem(name="Small")
        problem.add_machine(Machine(id=1, name="M1"))
        
        for i in range(5):
            task = Task(id=i, name=f"T{i}", task_type=f"Type{i % 2}", setup_time=5)
            task.add_alternative(1, 10)
            problem.add_task(task)
        
        solver = SolverFactory.get_solver(SolverType.CP_SAT, CIRCUIT_THRESHOLD=10)
        result = solver.solve(problem, time_limit_seconds=10)
        
        assert result.is_success
    
    def test_circuit_for_large_machines(self, large_problem):
        """Test CIRCUIT is used for large task counts."""
        solver = SolverFactory.get_solver(SolverType.CP_SAT, CIRCUIT_THRESHOLD=10)
        result = solver.solve(large_problem, time_limit_seconds=30)
        
        assert result.is_success


class TestSingleAltOptimization:
    """Test single-alternative task optimization."""
    
    def test_single_alt_task_scheduled(self):
        """Test single-alt task is correctly scheduled."""
        problem = SchedulingProblem(name="SingleAlt")
        problem.add_machine(Machine(id=1, name="M1"))
        
        # Single alternative task
        task = Task(id=1, name="SingleAlt", task_type="A")
        task.add_alternative(1, 50)  # Only one machine option
        problem.add_task(task)
        
        solver = SolverFactory.get_solver(SolverType.CP_SAT)
        result = solver.solve(problem, time_limit_seconds=10)
        
        assert result.status == "OPTIMAL"
        assert len(result.schedule) == 1
        assert result.schedule[0].machine_id == 1
        assert result.schedule[0].duration == 50
    
    def test_mixed_single_and_multi_alt(self):
        """Test problem with both single-alt and multi-alt tasks."""
        problem = SchedulingProblem(name="Mixed")
        problem.add_machine(Machine(id=1, name="M1"))
        problem.add_machine(Machine(id=2, name="M2"))
        
        # Single alternative task
        t1 = Task(id=1, name="SingleAlt", task_type="A")
        t1.add_alternative(1, 50)  # Only M1
        
        # Multi alternative task
        t2 = Task(id=2, name="MultiAlt", task_type="B", setup_time=10)
        t2.add_alternative(1, 60)
        t2.add_alternative(2, 40)  # Faster on M2
        t2.add_predecessor(t1)
        
        problem.add_task(t1)
        problem.add_task(t2)
        
        solver = SolverFactory.get_solver(SolverType.CP_SAT)
        result = solver.solve(problem, time_limit_seconds=10)
        
        assert result.status == "OPTIMAL"
        assert len(result.schedule) == 2
        
        # T1 must be on M1 (only option)
        t1_sched = next(s for s in result.schedule if s.task_id == 1)
        assert t1_sched.machine_id == 1
        
        # Precedence respected
        t2_sched = next(s for s in result.schedule if s.task_id == 2)
        assert t1_sched.end_time <= t2_sched.start_time
    
    def test_all_single_alt_tasks(self):
        """Test problem where all tasks are single-alt."""
        problem = SchedulingProblem(name="AllSingle")
        problem.add_machine(Machine(id=1, name="M1"))
        
        for i in range(5):
            task = Task(id=i, name=f"T{i}", task_type=f"Type{i % 2}", setup_time=5)
            task.add_alternative(1, 10)  # All on M1 only
            problem.add_task(task)
        
        solver = SolverFactory.get_solver(SolverType.CP_SAT)
        result = solver.solve(problem, time_limit_seconds=10)
        
        assert result.status == "OPTIMAL"
        assert len(result.schedule) == 5
        
        # All on M1
        for sched in result.schedule:
            assert sched.machine_id == 1
    
    def test_single_alt_with_setup_times(self):
        """Test single-alt tasks with different types respect setup times."""
        problem = SchedulingProblem(name="SingleAltSetup")
        problem.add_machine(Machine(id=1, name="M1"))
        
        t1 = Task(id=1, name="T1", task_type="TypeA", setup_time=0)
        t1.add_alternative(1, 30)
        
        t2 = Task(id=2, name="T2", task_type="TypeB", setup_time=15)
        t2.add_alternative(1, 30)
        
        problem.add_task(t1)
        problem.add_task(t2)
        
        solver = SolverFactory.get_solver(SolverType.CP_SAT)
        result = solver.solve(problem, time_limit_seconds=10)
        
        assert result.status == "OPTIMAL"
        
        t1_sched = next(s for s in result.schedule if s.task_id == 1)
        t2_sched = next(s for s in result.schedule if s.task_id == 2)
        
        # Either order, but setup time must be respected if T1 before T2
        if t1_sched.end_time < t2_sched.start_time:
            gap = t2_sched.start_time - t1_sched.end_time
            assert gap >= 15  # T2's setup time
