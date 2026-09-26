"""
Weighted Shortest Processing Time (WSPT) heuristic solver.

Schedules tasks by their processing time / priority ratio.
Optimizes for: Minimizing weighted completion time.
"""

from dataclasses import dataclass

from kairos.domain.models import ProblemFeature, Task
from kairos.solvers.heuristics.base import BaseHeuristicSolver


@dataclass
class WSPTSolver(BaseHeuristicSolver):
    """
    Weighted Shortest Processing Time dispatching rule (Smith's Rule).
    
    Priority: Tasks with lower (processing time / weight) ratio first.
    Weight is taken from task's job priority (default=1).
    
    Optimal for:
    - Minimizing total weighted completion time on single machine
    - High-priority short tasks get scheduled first
    
    Usage:
        solver = SolverFactory.get_solver(SolverType.WSPT)
        result = solver.solve(problem)
    """
    
    @property
    def name(self) -> str:
        return "WSPT Heuristic"
    
    @property
    def ignored_features(self) -> ProblemFeature:
        """WSPT ignores due dates - sorts by duration/weight ratio only."""
        return ProblemFeature.DUE_DATES
    
    @property
    def supported_features(self) -> ProblemFeature:
        """WSPT supports single and identical parallel machines, tolerates due dates."""
        return ProblemFeature.MULTI_MACHINE | ProblemFeature.DUE_DATES
    
    def _get_priority(self, task: Task) -> float:
        """Lower (duration / weight) ratio = higher priority."""
        if not task.alternatives:
            return float('inf')
        
        duration = min(task.alternatives.values())
        weight = task.priority if task.priority > 0 else 1
        
        # Smith's rule: p_j / w_j ratio
        return duration / weight
