"""
McNaughton's Wrap-Around Algorithm for preemptive parallel machine scheduling.

Optimal for: Minimizing makespan (Cmax) with preemption on identical parallel machines.
Cmax = max(max_job_duration, total_processing_time / num_machines)
"""

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Union

from kairos.domain.models import (
    Machine,
    ProblemFeature,
    ScheduledTask,
    SchedulingProblem,
    SolutionResult,
    Task,
)
from kairos.solvers.base_solver import BaseSolver
from kairos.solvers.factory import ObjectiveType


@dataclass
class McNaughtonSolver(BaseSolver):
    """
    McNaughton's Wrap-Around Algorithm.
    
    Optimal for minimizing makespan (Cmax) on identical parallel machines
    with preemption allowed.
    
    The algorithm:
    1. Calculate optimal Cmax = max(longest_job, total_time / num_machines)
    2. Pack tasks into machines using wrap-around when a task exceeds machine capacity
    
    Usage:
        solver = SolverFactory.get_solver(SolverType.MCNAUGHTON)
        result = solver.solve(problem)
    """
    
    @property
    def name(self) -> str:
        return "McNaughton's Algorithm"
    
    @property
    def required_features(self) -> ProblemFeature:
        """McNaughton requires preemption."""
        return ProblemFeature.PREEMPTION
    
    @property
    def ignored_features(self) -> ProblemFeature:
        """McNaughton ignores due dates."""
        return ProblemFeature.DUE_DATES
    
    @property
    def supported_features(self) -> ProblemFeature:
        """McNaughton supports parallel machines with preemption. Does NOT support release times."""
        return (
            ProblemFeature.PREEMPTION |
            ProblemFeature.MULTI_MACHINE |
            ProblemFeature.DUE_DATES
        )
    
    def _solve_impl(
        self,
        problem: SchedulingProblem,
        time_limit_seconds: int
    ) -> SolutionResult:
        """
        Solve using McNaughton's wrap-around algorithm.
        """
        start_time = time.time()
        
        machines = list(problem.machines.values())
        num_machines = len(machines)
        
        self._log(logging.INFO, f"Starting {self.name}: {len(problem.tasks)} tasks, {num_machines} machines")
        
        # Calculate processing times (use first machine's duration)
        durations: Dict[Union[int, str], int] = {}
        for task in problem.tasks:
            first_machine_id = list(task.alternatives.keys())[0]
            durations[task.id] = task.alternatives[first_machine_id]
        
        # Calculate optimal Cmax
        max_duration = max(durations.values())
        total_time = sum(durations.values())
        optimal_cmax = max(max_duration, total_time / num_machines)
        
        self._log(logging.DEBUG, f"Optimal Cmax = max({max_duration}, {total_time}/{num_machines}) = {optimal_cmax}")
        
        # Sort tasks by LPT (Longest Processing Time) for McNaughton
        sorted_tasks = sorted(problem.tasks, key=lambda t: durations[t.id], reverse=True)
        
        # Pack tasks using wrap-around
        segments: List[Dict] = []
        machine_idx = 0
        machine_time = 0
        
        for task in sorted_tasks:
            remaining = durations[task.id]
            
            while remaining > 0:
                machine = machines[machine_idx]
                available = optimal_cmax - machine_time
                
                if available <= 0:
                    # Move to next machine
                    machine_idx += 1
                    machine_time = 0
                    continue
                
                run_time = min(remaining, available)
                
                segments.append({
                    'task': task,
                    'machine': machine,
                    'start': machine_time,
                    'end': machine_time + run_time
                })
                
                if run_time < remaining:
                    self._log(logging.DEBUG, f"{task.name} wraps around from {machine.name} to next machine")
                
                machine_time += run_time
                remaining -= run_time
                
                if machine_time >= optimal_cmax:
                    machine_idx += 1
                    machine_time = 0
        
        # Build schedule - one ScheduledTask per segment for proper visualization
        schedule: List[ScheduledTask] = []
        for seg in segments:
            schedule.append(ScheduledTask(
                task=seg['task'],
                machine=seg['machine'],
                start_time=seg['start'],
                end_time=seg['end'],
                duration=seg['end'] - seg['start']
            ))
        
        schedule.sort(key=lambda s: (s.machine.id, s.start_time))
        
        solve_time = time.time() - start_time
        result = SolutionResult(
            status="OPTIMAL",  # McNaughton gives optimal Cmax
            objective_type=self.objective_type,
            schedule=schedule,
            solve_time_seconds=solve_time
        )
        
        result.calculate_metrics(problem.jobs)
        
        # Override makespan with optimal Cmax (algorithm guarantees this)
        result.makespan = optimal_cmax
        result.objective_value = optimal_cmax
        
        self._log(logging.INFO, f"Solved in {solve_time:.4f}s - Optimal Cmax: {optimal_cmax}")
        
        return result
