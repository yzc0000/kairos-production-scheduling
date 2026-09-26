"""
Tests for BaseSolver: compatibility, horizon calculation, logging

Uses shared fixtures from conftest.py
"""

import pytest
from kairos.domain.models import (
    Task, Machine, SchedulingProblem, ProblemFeature, SolutionResult
)
from kairos import SolverFactory, SolverType


class TestBaseSolverCompatibility:
    """Tests for solver compatibility checking."""
    
    def test_compatible_empty_problem(self, cpsat_solver, empty_problem):
        """Test compatibility with empty problem."""
        can_solve, msg = cpsat_solver.can_solve(empty_problem)
        assert can_solve is True
    
    def test_compatible_simple_problem(self, cpsat_solver, multi_machine_problem):
        """Test compatibility with multi-machine problem."""
        can_solve, msg = cpsat_solver.can_solve(multi_machine_problem)
        assert can_solve is True
        assert msg == "Compatible"
    
    def test_supported_features(self, cpsat_solver):
        """Test that CP-SAT supports expected features."""
        features = cpsat_solver.supported_features
        
        assert ProblemFeature.MULTI_MACHINE in features
        assert ProblemFeature.SETUP_TIMES in features
        assert ProblemFeature.PRECEDENCE in features
        assert ProblemFeature.DUE_DATES in features
        assert ProblemFeature.VARIABLE_SPEED in features


class TestHorizonCalculation:
    """Tests for horizon calculation."""
    
    def test_horizon_empty_problem(self, cpsat_solver, empty_problem):
        """Test horizon for empty problem."""
        horizon = cpsat_solver._calculate_horizon(empty_problem)
        assert horizon > 0
    
    def test_horizon_single_task(self, cpsat_solver, simple_problem):
        """Test horizon for single task."""
        horizon = cpsat_solver._calculate_horizon(simple_problem)
        assert horizon >= 100
    
    def test_horizon_with_precedence(self, cpsat_solver):
        """Test horizon accounts for precedence chain."""
        problem = SchedulingProblem()
        problem.add_machine(Machine(id=1, name="M1"))
        
        t1 = Task(id=1, name="T1")
        t1.add_alternative(1, 100)
        
        t2 = Task(id=2, name="T2")
        t2.add_alternative(1, 100)
        t2.add_predecessor(t1)
        
        t3 = Task(id=3, name="T3")
        t3.add_alternative(1, 100)
        t3.add_predecessor(t2)
        
        problem.add_task(t1)
        problem.add_task(t2)
        problem.add_task(t3)
        
        horizon = cpsat_solver._calculate_horizon(problem)
        assert horizon >= 300
    
    def test_horizon_with_setup(self, cpsat_solver, large_problem):
        """Test horizon accounts for setup times."""
        horizon = cpsat_solver._calculate_horizon(large_problem)
        # 15 tasks * 10 + setup overhead
        assert horizon >= 150


class TestSolverLogging:
    """Tests for solver logging functionality."""
    
    def test_logging_disabled_by_default(self, cpsat_solver):
        """Test logging is disabled by default."""
        assert cpsat_solver.logging_enabled is False
    
    def test_logging_enabled(self, logging_solver):
        """Test logging can be enabled."""
        assert logging_solver.logging_enabled is True
    
    def test_ortools_logging_disabled_by_default(self, cpsat_solver):
        """Test OR-Tools logging is disabled by default."""
        assert cpsat_solver.ortools_logging is False
    
    def test_ortools_logging_enabled(self):
        """Test OR-Tools logging can be enabled."""
        solver = SolverFactory.get_solver(SolverType.CP_SAT, ortools_logging=True)
        assert solver.ortools_logging is True


class TestSolverName:
    """Tests for solver name property."""
    
    def test_cpsat_solver_name(self, cpsat_solver):
        """Test CP-SAT solver name."""
        assert cpsat_solver.name == "Google CP-SAT"


class TestIncompatibleStatus:
    """Tests for INCOMPATIBLE status handling."""
    
    def test_incompatible_result_structure(self):
        """Test that INCOMPATIBLE results have correct structure."""
        result = SolutionResult(
            status="INCOMPATIBLE",
            objective_type=None,
            message="Test incompatibility"
        )
        
        assert result.status == "INCOMPATIBLE"
        assert result.is_success is False
        assert "incompatibility" in result.message.lower()
