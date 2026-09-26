"""
Shortest Processing Time (SPT) heuristic solver.

Schedules tasks by shortest duration first.
Optimizes for: Minimizing average completion time.
"""

from dataclasses import dataclass

from kairos.domain.models import ProblemFeature, Task
from kairos.solvers.heuristics.base import BaseHeuristicSolver


@dataclass
class SPTSolver(BaseHeuristicSolver):
    """
    Shortest Processing Time first dispatching rule.
    
    Priority: Tasks with shorter processing times are scheduled first.
    
    Optimal for:
    - Minimizing average completion time on single machine
    - Minimizing average waiting time
    
    Usage:
        solver = SolverFactory.get_solver(SolverType.SPT)
        result = solver.solve(problem)
    """
    
    @property
    def name(self) -> str:
        return "SPT Heuristic"
    
    @property
    def ignored_features(self) -> ProblemFeature:
        """SPT ignores due dates - sorts by processing time only."""
        return ProblemFeature.DUE_DATES
    
    @property
    def supported_features(self) -> ProblemFeature:
        """SPT supports single and identical parallel machines, tolerates due dates."""
        return ProblemFeature.MULTI_MACHINE | ProblemFeature.DUE_DATES
    
    def _get_priority(self, task: Task) -> float:
        """Shorter duration = higher priority (scheduled first)."""
        if not task.alternatives:
            return float('inf')
        return min(task.alternatives.values())
