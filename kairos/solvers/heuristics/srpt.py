"""
Shortest Remaining Processing Time (SRPT) preemptive heuristic solver.

Schedules tasks by shortest remaining time, allowing preemption.
Optimizes for: Minimizing average completion time with preemption.
"""

import logging
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
class SRPTSolver(BaseSolver):
    """
    Shortest Remaining Processing Time preemptive dispatching rule.
    
    Priority: At each time point, schedule the task with shortest remaining time.
    Tasks can be interrupted (preempted) when a shorter task arrives.
    
    Optimal for:
    - Minimizing average completion time on single machine with preemption
    
    Requires PREEMPTION feature in problem.
    
    Usage:
        solver = SolverFactory.get_solver(SolverType.SRPT)
        result = solver.solve(problem)
    """
    
    @property
    def name(self) -> str:
        return "SRPT Heuristic"
    
    @property
    def required_features(self) -> ProblemFeature:
        """SRPT requires preemption to be allowed."""
        return ProblemFeature.PREEMPTION
    
    @property
    def ignored_features(self) -> ProblemFeature:
        """SRPT ignores due dates."""
        return ProblemFeature.DUE_DATES
    
    @property
    def supported_features(self) -> ProblemFeature:
        """SRPT supports parallel machines with preemption and release times."""
        return ProblemFeature.PREEMPTION | ProblemFeature.DUE_DATES | ProblemFeature.RELEASE_TIME | ProblemFeature.MULTI_MACHINE
    
    def _solve_impl(
        self,
        problem: SchedulingProblem,
        time_limit_seconds: int
    ) -> SolutionResult:
        """
        Solve using SRPT preemptive scheduling.
        
        Algorithm:
        1. At each time point, find task with shortest remaining time
        2. Schedule it until completion or a shorter task arrives
        3. Allow preemption - tasks can be interrupted and resumed
        """
        import time
        start_time = time.time()
        
        self._log(logging.INFO, f"Starting {self.name}: {len(problem.tasks)} tasks, {len(problem.machines)} machines")
        
        # Branch based on number of machines
        if len(problem.machines) == 1:
            return self._solve_single_machine(problem, start_time)
        else:
            return self._solve_multi_machine(problem, start_time)
    
    def _solve_single_machine(
        self,
        problem: SchedulingProblem,
        start_time: float
    ) -> SolutionResult:
        """Single machine SRPT with preemption."""
        import time
        
        machine = list(problem.machines.values())[0]
        
        # Build task lookup
        task_by_id: Dict[int | str, Task] = {t.id: t for t in problem.tasks}
        
        # Initialize remaining processing times
        remaining: Dict[int | str, int] = {}
        for task in problem.tasks:
            remaining[task.id] = task.alternatives[machine.id]
        
        # Track scheduling segments (preemptive = multiple segments per task)
        segments: List[Dict] = []
        
        # Get all event times (release times)
        pending_tasks = {t.id: t.release_time for t in problem.tasks}
        active_tasks: set = set()
        completed_tasks: set = set()
        current_time = 0
        
        while pending_tasks or active_tasks:
            # Activate tasks that have arrived
            for tid, release in list(pending_tasks.items()):
                if release <= current_time:
                    active_tasks.add(tid)
                    del pending_tasks[tid]
            
            # If no active tasks, jump to next release time
            if not active_tasks:
                if pending_tasks:
                    current_time = min(pending_tasks.values())
                    continue
                else:
                    break
            
            # Find task with shortest remaining time
            best_task_id = min(active_tasks, key=lambda tid: remaining[tid])
            best_task = task_by_id[best_task_id]
            
            # Find next event (task arrival or completion)
            next_arrival = min(pending_tasks.values()) if pending_tasks else float('inf')
            completion_time = current_time + remaining[best_task_id]
            
            if next_arrival < completion_time:
                # Preempt: run until next arrival
                run_duration = next_arrival - current_time
                self._log(logging.DEBUG, f"Time {current_time}: {best_task.name} runs for {run_duration} (preempted)")
            else:
                # Complete the task
                run_duration = remaining[best_task_id]
                self._log(logging.DEBUG, f"Time {current_time}: {best_task.name} completes (duration={run_duration})")
            
            segments.append({
                'task_id': best_task_id,
                'task': best_task,
                'start': current_time,
                'end': current_time + run_duration
            })
            
            remaining[best_task_id] -= run_duration
            current_time += run_duration
            
            # Remove if completed
            if remaining[best_task_id] == 0:
                active_tasks.remove(best_task_id)
                completed_tasks.add(best_task_id)
        
        # Build schedule - one ScheduledTask per segment for proper visualization
        schedule: List[ScheduledTask] = []
        for seg in segments:
            schedule.append(ScheduledTask(
                task=seg['task'],
                machine=machine,
                start_time=seg['start'],
                end_time=seg['end'],
                duration=seg['end'] - seg['start']
            ))
        
        # Sort by start time
        schedule.sort(key=lambda s: s.start_time)
        
        solve_time = time.time() - start_time
        result = SolutionResult(
            status="FEASIBLE",
            objective_type=self.objective_type,
            schedule=schedule,
            solve_time_seconds=solve_time
        )
        
        result.calculate_metrics(problem.jobs)
        
        if self.objective_type == ObjectiveType.MAKESPAN:
            result.objective_value = result.makespan
        elif self.objective_type == ObjectiveType.WEIGHTED_TARDINESS:
            result.objective_value = result.weighted_tardiness
        else:
            result.objective_value = result.makespan
        
        self._log(logging.INFO, f"Solved in {solve_time:.4f}s - Makespan: {result.makespan}")
        
        return result
    
    def _solve_multi_machine(
        self,
        problem: SchedulingProblem,
        start_time: float
    ) -> SolutionResult:
        """
        Multi-machine SRPT with preemption.
        
        Algorithm:
        - At each time point, assign shortest remaining tasks to available machines
        - When a shorter task arrives, preempt the longest running task
        """
        import time
        
        machines = list(problem.machines.values())
        num_machines = len(machines)
        self._log(logging.DEBUG, f"Multi-machine mode: {num_machines} machines")
        
        # Build task lookup
        task_by_id: Dict[int | str, Task] = {t.id: t for t in problem.tasks}
        
        # Initialize remaining processing times (use first machine's duration for simplicity)
        remaining: Dict[int | str, int] = {}
        for task in problem.tasks:
            # Use first available machine's duration
            first_machine_id = list(task.alternatives.keys())[0]
            remaining[task.id] = task.alternatives[first_machine_id]
        
        # Track segments per task
        segments: List[Dict] = []
        
        # Track state
        pending_tasks = {t.id: t.release_time for t in problem.tasks}
        active_tasks: set = set()
        running: Dict[int | str, int | str] = {}  # machine_id -> task_id
        machine_task: Dict[int | str, int | str | None] = {m.id: None for m in machines}
        current_time = 0
        
        while pending_tasks or active_tasks or any(machine_task.values()):
            # Activate released tasks
            for tid, release in list(pending_tasks.items()):
                if release <= current_time:
                    active_tasks.add(tid)
                    del pending_tasks[tid]
            
            # Collect all ready tasks (active + currently running)
            ready_tasks = list(active_tasks)
            for mid, tid in machine_task.items():
                if tid is not None and tid not in ready_tasks:
                    ready_tasks.append(tid)
            
            # Sort by remaining time
            ready_tasks.sort(key=lambda tid: remaining[tid])
            
            # Assign top m tasks to machines
            assigned: Dict[int | str, int | str] = {}
            for i, machine in enumerate(machines):
                if i < len(ready_tasks):
                    tid = ready_tasks[i]
                    assigned[machine.id] = tid
                    if tid in active_tasks:
                        active_tasks.remove(tid)
            
            # Check for preemption
            for mid, old_tid in machine_task.items():
                new_tid = assigned.get(mid)
                if old_tid is not None and old_tid != new_tid:
                    # Preemption happened
                    if remaining[old_tid] > 0:
                        active_tasks.add(old_tid)
                        self._log(logging.DEBUG, f"Time {current_time}: {task_by_id[old_tid].name} preempted on machine {mid}")
            
            machine_task = {m.id: assigned.get(m.id) for m in machines}
            
            # If nothing running, jump to next release
            if not any(machine_task.values()):
                if pending_tasks:
                    current_time = min(pending_tasks.values())
                    continue
                else:
                    break
            
            # Find next event time
            next_release = min(pending_tasks.values()) if pending_tasks else float('inf')
            next_completion = float('inf')
            for mid, tid in machine_task.items():
                if tid is not None:
                    comp_time = current_time + remaining[tid]
                    if comp_time < next_completion:
                        next_completion = comp_time
            
            next_event = min(next_release, next_completion)
            run_duration = next_event - current_time
            
            # Run tasks and record segments
            for mid, tid in machine_task.items():
                if tid is not None:
                    machine = problem.get_machine(mid)
                    task = task_by_id[tid]
                    segments.append({
                        'task_id': tid,
                        'task': task,
                        'machine': machine,
                        'start': current_time,
                        'end': current_time + run_duration
                    })
                    remaining[tid] -= run_duration
                    
                    if remaining[tid] == 0:
                        machine_task[mid] = None
                        self._log(logging.DEBUG, f"Time {current_time}: {task.name} completes on {machine.name}")
            
            current_time = next_event
        
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
        
        schedule.sort(key=lambda s: s.start_time)
        
        solve_time = time.time() - start_time
        result = SolutionResult(
            status="FEASIBLE",
            objective_type=self.objective_type,
            schedule=schedule,
            solve_time_seconds=solve_time
        )
        
        result.calculate_metrics(problem.jobs)
        
        if self.objective_type == ObjectiveType.MAKESPAN:
            result.objective_value = result.makespan
        elif self.objective_type == ObjectiveType.WEIGHTED_TARDINESS:
            result.objective_value = result.weighted_tardiness
        else:
            result.objective_value = result.makespan
        
        self._log(logging.INFO, f"Solved in {solve_time:.4f}s - Makespan: {result.makespan}")
        
        return result
