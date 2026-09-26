"""
Base class for heuristic solvers.

Provides common list scheduling algorithm for dispatching rule heuristics.
Supports single machine and identical parallel machines only.
"""

import logging
from abc import abstractmethod
from dataclasses import dataclass
from typing import Dict, List

from kairos.domain.models import (
    ProblemFeature,
    ScheduledTask,
    SchedulingProblem,
    SolutionResult,
    Task,
)
from kairos.solvers.base_solver import BaseSolver
from kairos.solvers.factory import ObjectiveType


@dataclass
class BaseHeuristicSolver(BaseSolver):
    """
    Base class for dispatching rule heuristics.
    
    Supports:
    - Single machine (1|n.a.|objective)
    - Identical parallel machines (Pm|n.a.|objective)
    
    Rejects (returns INCOMPATIBLE):
    - VARIABLE_SPEED (different durations on machines)
    - PRECEDENCE (task dependencies)
    - SETUP_TIMES (sequence-dependent setup)
    
    Subclasses must implement:
    - name: Solver name
    - supported_features: Which features this solver needs
    - _get_priority: Priority calculation for sorting
    
    Usage:
        solver = SolverFactory.get_solver(
            SolverType.SPT,
            objective_type=ObjectiveType.MAKESPAN,
            logging_enabled=True
        )
    """
    
    @property
    @abstractmethod
    def supported_features(self) -> ProblemFeature:
        """Each solver defines its own supported features."""
        pass
    
    @abstractmethod
    def _get_priority(self, task: Task) -> float:
        """
        Calculate priority for a task. Lower value = higher priority (scheduled first).
        
        Args:
            task: The task to calculate priority for.
            
        Returns:
            Priority value (lower = scheduled first).
        """
        pass
    
    def _solve_impl(
        self,
        problem: SchedulingProblem,
        time_limit_seconds: int
    ) -> SolutionResult:
        """
        Solve using list scheduling algorithm.
        
        Note: Edge cases (no machines, no tasks) and feature validation
        are already handled by BaseSolver.solve().
        """
        import time
        start_time = time.time()
        
        self._log(logging.INFO, f"Starting {self.name}: {len(problem.tasks)} tasks, {len(problem.machines)} machines")
        
        # Sort tasks by priority (lower = first)
        sorted_tasks = sorted(problem.tasks, key=self._get_priority)
        self._log(logging.DEBUG, f"Task order: {[t.name for t in sorted_tasks]}")
        
        schedule: List[ScheduledTask] = []
        
        # Single machine fast-path: simple sequential scheduling
        if len(problem.machines) == 1:
            self._log(logging.DEBUG, "Single machine detected - using sequential scheduling")
            machine = list(problem.machines.values())[0]
            current_time = 0
            
            for task in sorted_tasks:
                duration = task.alternatives[machine.id]
                schedule.append(ScheduledTask(
                    task=task,
                    machine=machine,
                    start_time=current_time,
                    end_time=current_time + duration,
                    duration=duration
                ))
                self._log(logging.DEBUG, f"Scheduled {task.name} on {machine.name}: [{current_time}, {current_time + duration}]")
                current_time += duration
        
        else:
            # Multi-machine: list scheduling (assign to earliest available)
            self._log(logging.DEBUG, f"Multi-machine ({len(problem.machines)}) - using list scheduling")
            machine_available: Dict[int | str, int] = {
                m_id: 0 for m_id in problem.machines.keys()
            }
            
            for task in sorted_tasks:
                # Get machines this task can run on
                available_machines = [
                    m_id for m_id in task.alternatives.keys()
                    if m_id in problem.machines
                ]
                
                # Pick machine with earliest available time
                best_machine_id = min(
                    available_machines,
                    key=lambda m: machine_available[m]
                )
                
                machine = problem.get_machine(best_machine_id)
                duration = task.alternatives[best_machine_id]
                start = machine_available[best_machine_id]
                end = start + duration
                
                schedule.append(ScheduledTask(
                    task=task,
                    machine=machine,
                    start_time=start,
                    end_time=end,
                    duration=duration
                ))
                
                self._log(logging.DEBUG, f"Scheduled {task.name} on {machine.name}: [{start}, {end}]")
                
                # Update machine availability
                machine_available[best_machine_id] = end
        
        # Build result
        solve_time = time.time() - start_time
        result = SolutionResult(
            status="FEASIBLE",
            objective_type=self.objective_type,
            schedule=schedule,
            solve_time_seconds=solve_time
        )
        
        # Calculate all metrics
        result.calculate_metrics(problem.jobs)
        
        # Set objective_value based on objective_type
        if self.objective_type == ObjectiveType.MAKESPAN:
            result.objective_value = result.makespan
        elif self.objective_type == ObjectiveType.WEIGHTED_TARDINESS:
            result.objective_value = result.weighted_tardiness
        else:
            result.objective_value = result.makespan
        
        self._log(logging.INFO, f"Solved in {solve_time:.4f}s - Makespan: {result.makespan}, Objective: {result.objective_value}")
        
        return result


