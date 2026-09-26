"""
Tests for heuristic solvers.

Tests BaseHeuristicSolver and individual dispatching rule solvers.
All solvers accessed via SolverFactory.
Fixtures are defined in conftest.py
"""

import pytest
from kairos import Task, Job, Machine, SchedulingProblem
from kairos import SolverFactory, SolverType
from kairos.domain.models import ProblemFeature


# ============================================================
# BaseHeuristicSolver Tests (uses internal import for base class testing)
# ============================================================

class TestBaseHeuristicSolverValidation:
    """Test that base solver rejects complex features via can_solve()."""
    
    def test_rejects_variable_speed(self, variable_speed_problem):
        """VARIABLE_SPEED problems should be rejected by heuristics."""
        solver = SolverFactory.get_solver(SolverType.SPT)
        can_solve, message = solver.can_solve(variable_speed_problem)
        
        assert can_solve is False
        assert "VARIABLE_SPEED" in message
    
    def test_rejects_precedence(self, precedence_problem):
        """PRECEDENCE problems should be rejected by heuristics."""
        solver = SolverFactory.get_solver(SolverType.SPT)
        can_solve, message = solver.can_solve(precedence_problem)
        
        assert can_solve is False
        assert "PRECEDENCE" in message
    
    def test_rejects_setup_times(self, setup_times_problem):
        """SETUP_TIMES problems should be rejected by heuristics."""
        solver = SolverFactory.get_solver(SolverType.SPT)
        can_solve, message = solver.can_solve(setup_times_problem)
        
        assert can_solve is False
        assert "SETUP_TIMES" in message


class TestBaseHeuristicSolverListScheduling:
    """Test list scheduling algorithm."""
    
    def test_single_machine_scheduling(self, uniform_single_machine_problem):
        """Single machine should schedule sequentially."""
        solver = SolverFactory.get_solver(SolverType.SPT)
        result = solver.solve(uniform_single_machine_problem)
        
        assert result.status == "FEASIBLE"
        assert len(result.schedule) == 3
        # Makespan = 10 + 20 + 30 = 60
        assert result.objective_value == 60
    
    def test_parallel_machines_load_balancing(self, uniform_parallel_machines_problem):
        """Parallel machines should distribute load."""
        solver = SolverFactory.get_solver(SolverType.SPT)
        result = solver.solve(uniform_parallel_machines_problem)
        
        assert result.status == "FEASIBLE"
        assert len(result.schedule) == 4
        # 4 tasks × 20 min / 2 machines = 40 min makespan
        assert result.objective_value == 40
    
    def test_empty_problem(self):
        """Empty problem should return 0 makespan."""
        problem = SchedulingProblem(name="Empty")
        problem.add_machine(Machine(id=1, name="M1"))
        
        solver = SolverFactory.get_solver(SolverType.SPT)
        result = solver.solve(problem)
        
        assert result.status == "OPTIMAL"
        assert result.objective_value == 0


# ============================================================
# SPT Solver Tests
# ============================================================

class TestSPTSolver:
    """Tests for SPTSolver - Shortest Processing Time first."""
    
    def test_spt_solver_name(self):
        """Test solver name."""
        solver = SolverFactory.get_solver(SolverType.SPT)
        assert solver.name == "SPT Heuristic"
    
    def test_spt_shortest_first(self):
        """Test that SPT schedules shortest tasks first."""
        problem = SchedulingProblem(name="SPT Test")
        problem.add_machine(Machine(id=1, name="M1"))
        
        t1 = Task(id=1, name="Long")
        t1.add_alternative(1, 100)
        
        t2 = Task(id=2, name="Short")
        t2.add_alternative(1, 20)
        
        t3 = Task(id=3, name="Medium")
        t3.add_alternative(1, 50)
        
        problem.add_task(t1)
        problem.add_task(t2)
        problem.add_task(t3)
        
        solver = SolverFactory.get_solver(SolverType.SPT)
        result = solver.solve(problem)
        
        assert result.status == "FEASIBLE"
        # Should be ordered: Short (20), Medium (50), Long (100)
        assert result.schedule[0].task_name == "Short"
        assert result.schedule[1].task_name == "Medium"
        assert result.schedule[2].task_name == "Long"
    
    def test_spt_parallel_machines(self):
        """Test SPT on parallel machines."""
        problem = SchedulingProblem(name="SPT Parallel")
        problem.add_machine(Machine(id=1, name="M1"))
        problem.add_machine(Machine(id=2, name="M2"))
        
        for i in range(4):
            task = Task(id=i, name=f"T{i}")
            task.add_alternative(1, 30)
            task.add_alternative(2, 30)
            problem.add_task(task)
        
        solver = SolverFactory.get_solver(SolverType.SPT)
        result = solver.solve(problem)
        
        assert result.status == "FEASIBLE"
        # 4 tasks × 30 min / 2 machines = 60 min makespan
        assert result.objective_value == 60


# ============================================================
# LPT Solver Tests
# ============================================================

class TestLPTSolver:
    """Tests for LPTSolver - Longest Processing Time first."""
    
    def test_lpt_solver_name(self):
        """Test solver name."""
        solver = SolverFactory.get_solver(SolverType.LPT)
        assert solver.name == "LPT Heuristic"
    
    def test_lpt_longest_first(self):
        """Test that LPT schedules longest tasks first."""
        problem = SchedulingProblem(name="LPT Test")
        problem.add_machine(Machine(id=1, name="M1"))
        
        t1 = Task(id=1, name="Long")
        t1.add_alternative(1, 100)
        
        t2 = Task(id=2, name="Short")
        t2.add_alternative(1, 20)
        
        t3 = Task(id=3, name="Medium")
        t3.add_alternative(1, 50)
        
        problem.add_task(t1)
        problem.add_task(t2)
        problem.add_task(t3)
        
        solver = SolverFactory.get_solver(SolverType.LPT)
        result = solver.solve(problem)
        
        assert result.status == "FEASIBLE"
        # Should be ordered: Long (100), Medium (50), Short (20)
        assert result.schedule[0].task_name == "Long"
        assert result.schedule[1].task_name == "Medium"
        assert result.schedule[2].task_name == "Short"
    
    def test_lpt_load_balancing(self):
        """Test LPT provides better load balancing on parallel machines."""
        problem = SchedulingProblem(name="LoadBalance")
        problem.add_machine(Machine(id=1, name="M1"))
        problem.add_machine(Machine(id=2, name="M2"))
        
        durations = [100, 80, 40, 20]
        for i, dur in enumerate(durations):
            task = Task(id=i, name=f"T{i}")
            task.add_alternative(1, dur)
            task.add_alternative(2, dur)
            problem.add_task(task)
        
        solver = SolverFactory.get_solver(SolverType.LPT)
        result = solver.solve(problem)
        
        # LPT: M1 gets 100+20=120, M2 gets 80+40=120 → balanced makespan
        assert result.status == "FEASIBLE"
        assert result.objective_value == 120


# ============================================================
# EDD Solver Tests
# ============================================================

class TestEDDSolver:
    """Tests for EDDSolver - Earliest Due Date first."""
    
    def test_edd_solver_name(self):
        """Test solver name."""
        solver = SolverFactory.get_solver(SolverType.EDD)
        assert solver.name == "EDD Heuristic"
    
    def test_edd_earliest_due_date_first(self, problem_with_due_dates):
        """Test that EDD schedules by due date."""
        solver = SolverFactory.get_solver(SolverType.EDD)
        result = solver.solve(problem_with_due_dates)
        
        assert result.status == "FEASIBLE"
        assert len(result.schedule) == 2
        
        # Job2 has due_date=50, Job1 has due_date=100
        # So T2 (Job2) should come before T1 (Job1)
        assert result.schedule[0].task_name == "T2"
        assert result.schedule[1].task_name == "T1"
    
    def test_edd_supports_due_dates_feature(self):
        """Test EDD supports DUE_DATES feature."""
        solver = SolverFactory.get_solver(SolverType.EDD)
        assert ProblemFeature.DUE_DATES in solver.supported_features
    
    def test_edd_tasks_without_due_date_last(self):
        """Tasks without due dates should be scheduled last."""
        problem = SchedulingProblem(name="MixedDueDates")
        problem.add_machine(Machine(id=1, name="M1"))
        
        job1 = Job(id="J1", name="Urgent", due_date=50)
        t1 = Task(id=1, name="UrgentTask")
        t1.add_alternative(1, 30)
        job1.add_task(t1)
        
        t2 = Task(id=2, name="NoDueDate")
        t2.add_alternative(1, 20)
        
        problem.add_job(job1)
        problem.add_task(t2)
        
        solver = SolverFactory.get_solver(SolverType.EDD)
        result = solver.solve(problem)
        
        # UrgentTask (due_date=50) first, NoDueDate (inf) last
        assert result.schedule[0].task_name == "UrgentTask"
        assert result.schedule[1].task_name == "NoDueDate"


# ============================================================
# WSPT Solver Tests
# ============================================================

class TestWSPTSolver:
    """Tests for WSPTSolver (Smith's Rule)."""
    
    def test_wspt_solver_name(self):
        """Test solver name."""
        solver = SolverFactory.get_solver(SolverType.WSPT)
        assert solver.name == "WSPT Heuristic"
    
    def test_wspt_priority_ordering(self):
        """Test WSPT uses duration/weight ratio."""
        problem = SchedulingProblem(name="WSPT Test")
        problem.add_machine(Machine(id=1, name="M1"))
        
        # Job1: duration=100, priority=10 → ratio=10
        job1 = Job(id="J1", name="LowRatio", priority=10)
        t1 = Task(id=1, name="HighPriorityLong")
        t1.add_alternative(1, 100)
        job1.add_task(t1)
        
        # Job2: duration=50, priority=1 → ratio=50
        job2 = Job(id="J2", name="HighRatio", priority=1)
        t2 = Task(id=2, name="LowPriorityShort")
        t2.add_alternative(1, 50)
        job2.add_task(t2)
        
        problem.add_job(job1)
        problem.add_job(job2)
        
        solver = SolverFactory.get_solver(SolverType.WSPT)
        result = solver.solve(problem)
        
        assert result.status == "FEASIBLE"
        # HighPriorityLong (ratio=10) before LowPriorityShort (ratio=50)
        assert result.schedule[0].task_name == "HighPriorityLong"
        assert result.schedule[1].task_name == "LowPriorityShort"
    
    def test_wspt_default_priority(self):
        """Tasks without jobs use priority=1."""
        problem = SchedulingProblem(name="WSPT Default")
        problem.add_machine(Machine(id=1, name="M1"))
        
        t1 = Task(id=1, name="Short")
        t1.add_alternative(1, 20)  # ratio = 20/1 = 20
        
        t2 = Task(id=2, name="Long")
        t2.add_alternative(1, 100)  # ratio = 100/1 = 100
        
        problem.add_task(t1)
        problem.add_task(t2)
        
        solver = SolverFactory.get_solver(SolverType.WSPT)
        result = solver.solve(problem)
        
        # Short (ratio=20) before Long (ratio=100)
        assert result.schedule[0].task_name == "Short"
        assert result.schedule[1].task_name == "Long"


# ============================================================
# SRPT Solver Tests
# ============================================================

class TestSRPTSolver:
    """Test SRPT (Shortest Remaining Processing Time) preemptive solver."""
    
    def test_srpt_requires_preemption(self, no_preemption_problem):
        """SRPT should reject problems without preemption enabled."""
        solver = SolverFactory.get_solver(SolverType.SRPT)
        can_solve, message = solver.can_solve(no_preemption_problem)
        
        assert can_solve is False
        assert "PREEMPTION" in message
    
    def test_srpt_accepts_preemption(self, preemption_single_machine):
        """SRPT should accept problems with preemption enabled."""
        solver = SolverFactory.get_solver(SolverType.SRPT)
        can_solve, _ = solver.can_solve(preemption_single_machine)
        
        assert can_solve is True
    
    def test_srpt_single_machine_preemption(self, preemption_single_machine):
        """SRPT should preempt long task when shorter task arrives."""
        solver = SolverFactory.get_solver(SolverType.SRPT)
        result = solver.solve(preemption_single_machine)
        
        assert result.status == "FEASIBLE"
        
        # Both tasks should be scheduled
        task_names = {s.task_name for s in result.schedule}
        assert task_names == {"Short", "Long"}
        
        # Long task should have 2 segments (preempted), Short task should have 1
        long_segments = [s for s in result.schedule if s.task_name == "Long"]
        short_segments = [s for s in result.schedule if s.task_name == "Short"]
        assert len(long_segments) == 2  # preempted
        assert len(short_segments) == 1
        
        # Makespan should be 120
        assert result.makespan == 120
    
    def test_srpt_multi_machine(self, preemption_multi_machine):
        """SRPT should work with multiple machines."""
        solver = SolverFactory.get_solver(SolverType.SRPT)
        result = solver.solve(preemption_multi_machine)
        
        assert result.status == "FEASIBLE"
        
        # All tasks should be scheduled
        task_names = {s.task_name for s in result.schedule}
        assert task_names == {"T1", "T2", "T3"}
    
    def test_srpt_shortest_first_no_release(self):
        """Without release times, SRPT behaves like SPT."""
        problem = SchedulingProblem(name="NoRelease")
        problem.enable_preemption()
        problem.add_machine(Machine(id=1, name="M1"))
        
        t1 = Task(id=1, name="Long")
        t1.add_alternative(1, 100)
        
        t2 = Task(id=2, name="Short")
        t2.add_alternative(1, 20)
        
        problem.add_task(t1)
        problem.add_task(t2)
        
        solver = SolverFactory.get_solver(SolverType.SRPT)
        result = solver.solve(problem)
        
        # Short first, then Long (like SPT)
        assert result.schedule[0].task_name == "Short"
        assert result.schedule[1].task_name == "Long"
        assert result.makespan == 120


# ============================================================
# McNaughton Solver Tests
# ============================================================

class TestMcNaughtonSolver:
    """Test McNaughton's Wrap-Around Algorithm."""
    
    def test_mcnaughton_requires_preemption(self, no_preemption_problem):
        """McNaughton should reject problems without preemption enabled."""
        solver = SolverFactory.get_solver(SolverType.MCNAUGHTON)
        can_solve, message = solver.can_solve(no_preemption_problem)
        
        assert can_solve is False
        assert "PREEMPTION" in message
    
    def test_mcnaughton_optimal_cmax(self):
        """McNaughton should achieve optimal Cmax = max(longest, total/m)."""
        problem = SchedulingProblem(name="OptimalCmax")
        problem.enable_preemption()
        problem.add_machine(Machine(id=1, name="M1"))
        problem.add_machine(Machine(id=2, name="M2"))
        
        # 3 tasks x 4 = 12 total, 2 machines -> optimal = max(4, 12/2) = 6
        for i in range(3):
            t = Task(id=i, name=f"T{i}")
            t.add_alternative(1, 4)
            t.add_alternative(2, 4)
            problem.add_task(t)
        
        solver = SolverFactory.get_solver(SolverType.MCNAUGHTON)
        result = solver.solve(problem)
        
        assert result.status == "OPTIMAL"
        assert result.makespan == 6.0
    
    def test_mcnaughton_wrap_around(self):
        """Tasks should wrap around to next machine when necessary."""
        problem = SchedulingProblem(name="WrapAround")
        problem.enable_preemption()
        problem.add_machine(Machine(id=1, name="M1"))
        problem.add_machine(Machine(id=2, name="M2"))
        
        # Tasks: 4 + 4 + 4 = 12, 2 machines -> Cmax = 6
        # T1 fits on M1 [0-4], T2 splits: M1[4-6] + M2[0-2], T3: M2[2-6]
        t1 = Task(id=1, name="T1")
        t1.add_alternative(1, 4)
        t1.add_alternative(2, 4)
        
        t2 = Task(id=2, name="T2")
        t2.add_alternative(1, 4)
        t2.add_alternative(2, 4)
        
        t3 = Task(id=3, name="T3")
        t3.add_alternative(1, 4)
        t3.add_alternative(2, 4)
        
        problem.add_task(t1)
        problem.add_task(t2)
        problem.add_task(t3)
        
        solver = SolverFactory.get_solver(SolverType.MCNAUGHTON)
        result = solver.solve(problem)
        
        # T2 should have 2 segments (wrap-around)
        t2_segments = [s for s in result.schedule if s.task_name == "T2"]
        assert len(t2_segments) == 2
    
    def test_mcnaughton_single_machine(self):
        """Single machine should still work (no wrap-around)."""
        problem = SchedulingProblem(name="SingleMachine")
        problem.enable_preemption()
        problem.add_machine(Machine(id=1, name="M1"))
        
        t1 = Task(id=1, name="T1")
        t1.add_alternative(1, 10)
        t2 = Task(id=2, name="T2")
        t2.add_alternative(1, 20)
        
        problem.add_task(t1)
        problem.add_task(t2)
        
        solver = SolverFactory.get_solver(SolverType.MCNAUGHTON)
        result = solver.solve(problem)
        
        assert result.makespan == 30  # max(20, 30/1) = 30
