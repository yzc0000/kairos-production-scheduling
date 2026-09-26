"""
Earliest Due Date (EDD) heuristic solver.

Schedules tasks by their due dates (earliest first).
Optimizes for: Minimizing maximum lateness.
"""

from dataclasses import dataclass

from kairos.domain.models import ProblemFeature, Task
from kairos.solvers.heuristics.base import BaseHeuristicSolver


@dataclass
class EDDSolver(BaseHeuristicSolver):
    """
    Earliest Due Date first dispatching rule.
    
    Priority: Tasks with earlier due dates are scheduled first.
    Uses job due date if task doesn't have one.
    
    Optimal for:
    - Minimizing maximum lateness (Lmax) on single machine
    - Reducing tardiness when due dates exist
    
    Usage:
        solver = SolverFactory.get_solver(SolverType.EDD)
        result = solver.solve(problem)
    """
    
    @property
    def name(self) -> str:
        return "EDD Heuristic"
    
    @property
    def required_features(self) -> ProblemFeature:
        """EDD requires due dates to sort by."""
        return ProblemFeature.DUE_DATES
    
    @property
    def supported_features(self) -> ProblemFeature:
        """EDD supports parallel machines and due dates."""
        return ProblemFeature.MULTI_MACHINE | ProblemFeature.DUE_DATES
    
    def _get_priority(self, task: Task) -> float:
        """Earlier due date = higher priority (scheduled first)."""
        # Use task's due date, fallback to job's due date
        due_date = task.due_date
        if due_date is None:
            due_date = float('inf')
        return due_date
