"""
Abstract base class for all scheduling solvers.

Provides the capability checking mechanism that ensures solvers
only attempt to solve problems they can handle.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Tuple, Union

from kairos.domain.models import SchedulingProblem, SolutionResult, ProblemFeature

# Base logger for all solvers
_logger = logging.getLogger("kairos.solvers")


def _configure_kairos_logging():
    """Configure kairos logging with a handler if none exists."""
    if not _logger.handlers and not logging.getLogger().handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '%(name)s - %(levelname)s - %(message)s'
        ))
        _logger.addHandler(handler)
        _logger.setLevel(logging.DEBUG)


@dataclass
class BaseSolver(ABC):
    """
    Abstract base class for scheduling solvers.
    
    All solver implementations must inherit from this class and implement:
    - supported_features: Property declaring what problem features this solver handles
    - _solve_impl: The actual solving logic
    
    The base class provides automatic compatibility checking via can_solve().
    
    Attributes:
        logging_enabled: Enable solver logging (constraint types, timing)
        objective_type: Objective function to optimize (MAKESPAN or WEIGHTED_TARDINESS)
    """
    
    # Logging options
    logging_enabled: bool = False
    
    # Objective function selection
    objective_type: int = 0  # ObjectiveType.MAKESPAN
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of the solver."""
        pass
    
    @property
    @abstractmethod
    def supported_features(self) -> ProblemFeature:
        """
        Declare which problem features this solver supports.
        
        Returns a ProblemFeature flag combination representing all
        features this solver can handle.
        """
        pass
    
    @property
    def required_features(self) -> ProblemFeature:
        """
        Declare which features the problem MUST have for this solver to work.
        
        Override in subclasses that require specific features.
        For example, EDD requires DUE_DATES, SRPT requires PREEMPTION.
        
        Default: NONE (no required features).
        """
        return ProblemFeature.NONE
    
    @property
    def ignored_features(self) -> ProblemFeature:
        """
        Declare which features this solver will IGNORE if present.
        
        These features won't cause incompatibility, but the solver
        won't use them in the solution. User will be warned.
        
        Default: NONE (no ignored features).
        """
        return ProblemFeature.NONE
    
    def can_solve(self, problem: SchedulingProblem) -> Tuple[bool, str]:
        """
        Check if this solver can handle the given problem.
        
        Validates:
        1. Problem contains all required_features (solver needs these)
        2. Problem doesn't have unsupported features (solver can't handle)
        3. Warns if problem has ignored_features (will be ignored)
        
        Args:
            problem: The scheduling problem to check.
            
        Returns:
            Tuple of (is_compatible, message).
        """
        problem_features = problem.get_features()
        
        # Check required features (problem must have these)
        missing = self.required_features & ~problem_features
        if missing:
            feature_names = str(missing).replace("ProblemFeature.", "")
            return (
                False,
                f"This solver ({self.name}) requires features not present in problem: {feature_names}"
            )
        
        # Check unsupported features (problem can't have these)
        unsupported = problem_features & ~self.supported_features
        if unsupported:
            feature_names = str(unsupported).replace("ProblemFeature.", "")
            return (
                False,
                f"This solver ({self.name}) is not compatible with this problem type. "
                f"Unsupported features: {feature_names}"
            )
        
        # Check ignored features (will be ignored, warn user)
        ignored = problem_features & self.ignored_features
        if ignored:
            feature_names = str(ignored).replace("ProblemFeature.", "")
            return (
                True,
                f"Compatible (warning: {feature_names} will be ignored by {self.name})"
            )
        
        return True, "Compatible"
    
    def solve(self, problem: SchedulingProblem, time_limit_seconds: int = 60) -> SolutionResult:
        """
        Solve the scheduling problem.
        
        First checks compatibility and edge cases, then delegates to _solve_impl.
        
        Args:
            problem: The scheduling problem to solve.
            time_limit_seconds: Maximum time allowed for solving.
            
        Returns:
            SolutionResult with status, schedule, and objective value.
        """
        # Edge case: no machines
        if not problem.machines:
            return SolutionResult(
                status="INFEASIBLE",
                message="No machines defined in problem."
            )
        
        # Edge case: no tasks
        if not problem.tasks:
            return SolutionResult(
                status="OPTIMAL",
                objective_value=0,
                schedule=[],
                message="No tasks to schedule."
            )
        
        # Validation: check all tasks have valid machine alternatives
        for task in problem.tasks:
            valid_machines = [m for m in task.alternatives.keys() if m in problem.machines]
            if not valid_machines:
                return SolutionResult(
                    status="INFEASIBLE",
                    message=f"Task {task.id} ({task.name}) has no valid machine alternatives."
                )
        
        # Check compatibility
        is_compatible, message = self.can_solve(problem)
        if not is_compatible:
            return SolutionResult(
                status="INCOMPATIBLE",
                objective_type=None,
                message=message
            )
        
        # Delegate to implementation
        return self._solve_impl(problem, time_limit_seconds)
    
    @abstractmethod
    def _solve_impl(self, problem: SchedulingProblem, time_limit_seconds: int) -> SolutionResult:
        """
        Actual solving implementation.
        
        This method is called only after compatibility has been verified.
        Subclasses must implement this method.
        """
        pass

    
    def _log(self, level: int, message: str) -> None:
        """
        Log message only if logging is enabled.
        
        Auto-configures logging handler if needed.
        All solvers can use this method.
        """
        if self.logging_enabled:
            _configure_kairos_logging()
            # Use solver-specific logger with class name
            logger = logging.getLogger(f"kairos.solvers.{self.__class__.__name__.lower()}")
            logger.setLevel(logging.DEBUG)
            logger.log(level, message)
    
    def _calculate_horizon(self, problem: SchedulingProblem) -> int:
        """
        Calculate a reasonable time horizon for the scheduling problem.
        
        The horizon is an upper bound on the makespan. Uses:
        1. Critical path through precedence DAG
        2. Machine contention (total work / machines)
        3. Maximum possible setup times
        
        Returns:
            Upper bound on makespan in time units.
        """
        if not problem.tasks:
            return 10000
        
        num_machines = max(len(problem.machines), 1)
        
        # 1. Calculate minimum duration for each task
        task_min_dur = {}
        for task in problem.tasks:
            if task.alternatives:
                task_min_dur[task.id] = min(task.alternatives.values())
            else:
                task_min_dur[task.id] = 0
        
        # 2. Critical path through precedence DAG (longest path)
        # Dynamic programming: cp[task] = longest path ending at task
        task_by_id = {t.id: t for t in problem.tasks}
        critical_path_cache = {}
        
        def get_critical_path(task_id):
            if task_id in critical_path_cache:
                return critical_path_cache[task_id]
            
            task = task_by_id.get(task_id)
            if not task:
                return 0
            
            # Maximum path through predecessors + this task's duration
            max_pred_path = 0
            for pred in task.predecessors:
                pred_path = get_critical_path(pred.id)
                # Add setup time if different category
                setup = task.setup_time if pred.get_effective_task_type() != task.get_effective_task_type() else 0
                max_pred_path = max(max_pred_path, pred_path + setup)
            
            result = max_pred_path + task_min_dur.get(task_id, 0)
            critical_path_cache[task_id] = result
            return result
        
        critical_path_length = max(
            get_critical_path(t.id) for t in problem.tasks
        ) if problem.tasks else 0
        
        # 3. Machine contention: consider both average and maximum load
        total_work = sum(task_min_dur.values())
        avg_work_per_machine = total_work // num_machines
        
        # 4. Maximum load on any single machine (bottleneck)
        # Group tasks by their possible machines and find the bottleneck
        machine_min_load: Dict[Union[int, str], int] = {}
        for task in problem.tasks:
            if task.alternatives:
                # Assume task goes to its fastest machine
                min_duration = min(task.alternatives.values())
                # Add to ALL possible machines (conservative lower bound)
                for m_id in task.alternatives.keys():
                    if m_id not in machine_min_load:
                        machine_min_load[m_id] = 0
                    machine_min_load[m_id] += min_duration
        
        max_machine_load = max(machine_min_load.values()) if machine_min_load else 0
        
        # 5. Maximum setup overhead
        max_setup = max((t.setup_time for t in problem.tasks), default=0)
        setup_overhead = max_setup * len(problem.tasks) // num_machines
        
        # Horizon = max(critical_path, avg_work, max_machine_load) + setup overhead + buffer
        base_horizon = max(critical_path_length, avg_work_per_machine + setup_overhead, max_machine_load)
        
        return int(base_horizon * 1.5) + 100

