"""
Longest Processing Time (LPT) heuristic solver.

Schedules tasks by longest duration first.
Optimizes for: Load balancing on parallel machines.
"""

from dataclasses import dataclass

from kairos.domain.models import ProblemFeature, Task
from kairos.solvers.heuristics.base import BaseHeuristicSolver


@dataclass
class LPTSolver(BaseHeuristicSolver):
    """
    Longest Processing Time first dispatching rule.
    
    Priority: Tasks with longer processing times are scheduled first.
    
    Optimal for:
    - Better load balancing on identical parallel machines
    - Minimizing makespan on parallel machines (2-approximation)
    
    Usage:
        solver = SolverFactory.get_solver(SolverType.LPT)
        result = solver.solve(problem)
    """
    
    @property
    def name(self) -> str:
        return "LPT Heuristic"
    
    @property
    def ignored_features(self) -> ProblemFeature:
        """LPT ignores due dates - sorts by processing time only."""
        return ProblemFeature.DUE_DATES
    
    @property
    def supported_features(self) -> ProblemFeature:
        """LPT supports single and identical parallel machines, tolerates due dates."""
        return ProblemFeature.MULTI_MACHINE | ProblemFeature.DUE_DATES
    
    def _get_priority(self, task: Task) -> float:
        """Longer duration = higher priority (scheduled first)."""
        if not task.alternatives:
            return float('inf')
        # Negative because we want longest first
        return -max(task.alternatives.values())
