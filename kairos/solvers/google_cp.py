"""
Google OR-Tools CP-SAT solver for Assembly Job Shop scheduling.

Features:
- Multiple precedence constraints (assembly structure)
- Flexible machines (same task can run on different machines)
- Sequence-dependent setup times:
  - Same task_type → 0 setup
  - Different task_type → target task's setup_time

Hybrid constraint approach:
- NONE: 0-1 tasks on machine
- NO_OVERLAP: Single task_type (no setup needed)
- PAIRWISE: Few tasks per machine (< threshold)
- CIRCUIT: Many tasks per machine (>= threshold)
"""

import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

from ortools.sat.python import cp_model

from kairos.domain.models import (
    ProblemFeature,
    ScheduledTask,
    SchedulingProblem,
    SolutionResult,
    Task
)
from kairos.solvers.base_solver import BaseSolver
from kairos.solvers.factory import ObjectiveType



@dataclass
class GoogleCPSATSolver(BaseSolver):
    """
    Google OR-Tools CP-SAT solver for Assembly Job Shop.
    
    Supports:
    - Multiple precedence per task (DAG)
    - Flexible machine assignment
    - Sequence-dependent setup times (category-based)
    
    Usage:
        solver = SolverFactory.get_solver(SolverType.CP_SAT, logging_enabled=True)
    """

    # CP-SAT specific options
    CIRCUIT_THRESHOLD: int = 25  # Use CIRCUIT if n > this
    ortools_logging: bool = False  # Enable OR-Tools search progress logging
    
    # logging_enabled and objective_type inherited from BaseSolver

    @property
    def name(self) -> str:
        return "Google CP-SAT"

    @property
    def supported_features(self) -> ProblemFeature:
        return (
            ProblemFeature.MULTI_MACHINE |
            ProblemFeature.SETUP_TIMES |
            ProblemFeature.PRECEDENCE |
            ProblemFeature.DUE_DATES |
            ProblemFeature.VARIABLE_SPEED
        )

    def _solve_impl(
        self,
        problem: SchedulingProblem,
        time_limit_seconds: int
    ) -> SolutionResult:
        start_time = time.time()
        model = cp_model.CpModel()
        
        horizon = self._calculate_horizon(problem)
        
        self._log(logging.INFO, f"Starting solve: {len(problem.tasks)} tasks, {len(problem.machines)} machines")
        self._log(logging.DEBUG, f"Horizon: {horizon}, Time limit: {time_limit_seconds}s")
        
        # ===== MASTER VARIABLES =====
        master_start: Dict[Union[int, str], cp_model.IntVar] = {}
        master_end: Dict[Union[int, str], cp_model.IntVar] = {}
        
        for task in problem.tasks:
            master_start[task.id] = model.NewIntVar(0, horizon, f"ms_{task.id}")
            master_end[task.id] = model.NewIntVar(0, horizon, f"me_{task.id}")

        # ===== MACHINE VARIABLES =====
        task_vars: Dict[Union[int, str], Dict] = {}
        machine_tasks: Dict[Union[int, str], List[Dict]] = defaultdict(list)
        
        for task in problem.tasks:
            task_vars[task.id] = {}
            
            # Single alternative optimization: fix presence to 1
            is_single_alternative = len(task.alternatives) == 1
            
            for m_id, duration in task.alternatives.items():
                suffix = f"_{task.id}_{m_id}"
                
                start = model.NewIntVar(0, horizon, f"s{suffix}")
                end = model.NewIntVar(0, horizon, f"e{suffix}")
                presence = model.NewBoolVar(f"p{suffix}")
                
                # Fix presence to 1 if single alternative (no choice needed)
                if is_single_alternative:
                    model.Add(presence == 1)
                    self._log(logging.DEBUG, f"Task {task.id} ({task.name}): single-alt, presence fixed to 1")
                
                interval = model.NewOptionalIntervalVar(
                    start, duration, end, presence, f"iv{suffix}"
                )
                
                task_vars[task.id][m_id] = {
                    'start': start,
                    'end': end,
                    'interval': interval,
                    'presence': presence,
                    'duration': duration
                }
                
                machine_tasks[m_id].append({
                    'interval': interval,
                    'presence': presence,
                    'task': task,
                    'start': start,
                    'end': end,
                    'duration': duration
                })
                
                # Link to master variables
                model.Add(master_start[task.id] == start).OnlyEnforceIf(presence)
                model.Add(master_end[task.id] == end).OnlyEnforceIf(presence)

        # ===== EXACTLY ONE MACHINE PER TASK =====
        # Skip single-alternative tasks (presence already fixed to 1)
        single_alt_count = sum(1 for t in problem.tasks if len(t.alternatives) == 1)
        multi_alt_count = len(problem.tasks) - single_alt_count
        
        if single_alt_count > 0:
            self._log(logging.DEBUG, f"Single-alt optimization: {single_alt_count} tasks fixed, {multi_alt_count} with ExactlyOne")
        
        for task in problem.tasks:
            if task.id in task_vars and len(task.alternatives) > 1:
                presences = [v['presence'] for v in task_vars[task.id].values()]
                model.AddExactlyOne(presences)

        # ===== SYMMETRY BREAKING =====
        self._add_symmetry_breaking(model, problem, task_vars)

        # ===== PRECEDENCE CONSTRAINTS (DAG) =====
        for task in problem.tasks:
            for pred in task.predecessors:
                if pred.id in master_end and task.id in master_start:
                    model.Add(master_end[pred.id] <= master_start[task.id])

        # ===== MACHINE CONSTRAINTS + SETUP =====
        self._add_machine_constraints(model, machine_tasks)

        # ===== CALCULATE JOB COMPLETION TIMES =====
        # Job completion time = max end time of tasks in that job
        job_end: Dict[Union[int, str], cp_model.IntVar] = {}
        
        for job in problem.jobs:
            if job.tasks:
                task_ends = [master_end[t.id] for t in job.tasks if t.id in master_end]
                if task_ends:
                    job_end[job.id] = model.NewIntVar(0, horizon, f"job_end_{job.id}")
                    model.AddMaxEquality(job_end[job.id], task_ends)
        
        # Find standalone tasks (tasks not in any job)
        tasks_in_jobs = set()
        for job in problem.jobs:
            for task in job.tasks:
                tasks_in_jobs.add(task.id)
        
        standalone_ends = [master_end[t.id] for t in problem.tasks 
                          if t.id in master_end and t.id not in tasks_in_jobs]
        
        # All completion variables (jobs + standalone tasks)
        all_completion_vars = list(job_end.values()) + standalone_ends
        
        # ===== OBJECTIVE FUNCTION SELECTION =====
        # ObjectiveType: 0 = MAKESPAN, 1 = WEIGHTED_TARDINESS
        used_objective_type = ObjectiveType.MAKESPAN  # Default
        
        if self.objective_type == 1:  # WEIGHTED_TARDINESS
            self._log(logging.INFO, "Objective: WEIGHTED_TARDINESS")
            
            # Calculate tardiness for each job: max(0, job_end - due_date)
            tardiness_terms = []
            
            for job in problem.jobs:
                if job.id in job_end and job.due_date is not None:
                    # Tardiness = max(0, job_end - due_date)
                    tardiness = model.NewIntVar(0, horizon, f"tardiness_{job.id}")
                    model.AddMaxEquality(tardiness, [0, job_end[job.id] - job.due_date])
                    
                    # Weighted by priority
                    tardiness_terms.append(tardiness * job.priority)
            
            if tardiness_terms:
                model.Minimize(sum(tardiness_terms))
                used_objective_type = ObjectiveType.WEIGHTED_TARDINESS
            else:
                # Fallback to makespan if no jobs with due dates
                self._log(logging.WARNING, "No jobs with due dates, falling back to MAKESPAN")
                makespan = model.NewIntVar(0, horizon, "makespan")
                if all_completion_vars:
                    model.AddMaxEquality(makespan, all_completion_vars)
                else:
                    model.AddMaxEquality(makespan, list(master_end.values()))
                model.Minimize(makespan)
                used_objective_type = ObjectiveType.MAKESPAN  # Fallback applied
        else:  # MAKESPAN (default)
            self._log(logging.INFO, "Objective: MAKESPAN")
            makespan = model.NewIntVar(0, horizon, "makespan")
            if all_completion_vars:
                model.AddMaxEquality(makespan, all_completion_vars)
            else:
                model.AddMaxEquality(makespan, list(master_end.values()))
            model.Minimize(makespan)
            used_objective_type = ObjectiveType.MAKESPAN

        # ===== SOLVE =====
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.num_search_workers = os.cpu_count()
        
        # Enable OR-Tools search progress logging
        if self.ortools_logging:
            solver.parameters.log_search_progress = True
        
        status = solver.Solve(model)
        solve_time = time.time() - start_time
        
        status_str = self._status_to_string(status)
        
        # Determine objective label for logging
        obj_label = "weighted-tardiness" if used_objective_type == ObjectiveType.WEIGHTED_TARDINESS else "makespan"
        
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            schedule = self._extract_schedule(solver, problem, task_vars)
            
            # Calculate optimality gap
            best_obj = solver.ObjectiveValue()
            best_bound = solver.BestObjectiveBound()
            if best_obj != 0:
                gap = abs(best_obj - best_bound) / abs(best_obj) * 100
            else:
                gap = 0.0 if best_bound == 0 else float('inf')
            
            # Build result and calculate metrics using shared method
            result = SolutionResult(
                status=status_str,
                objective_type=used_objective_type,
                objective_value=int(best_obj),
                schedule=schedule,
                solve_time_seconds=solve_time,
                gap_percentage=round(gap, 2)
            )
            result.calculate_metrics(problem.jobs)
            
            gap_str = f", gap={gap:.2f}%" if gap > 0 else ""
            self._log(logging.INFO, f"Solved: {status_str}, {obj_label}={int(best_obj)}{gap_str}, time={solve_time:.2f}s")
            self._log(logging.INFO, f"Metrics: makespan={result.makespan}, "
                      f"weighted_tardiness={result.weighted_tardiness}, "
                      f"total_completion_time={result.total_completion_time}")
            
            return result
        else:
            self._log(logging.WARNING, f"Failed to solve: {status_str}")
            return SolutionResult(
                status=status_str,
                message=f"Could not solve. Status: {status_str}",
                solve_time_seconds=solve_time
            )

    def _add_machine_constraints(
        self,
        model: cp_model.CpModel,
        machine_tasks: Dict[Union[int, str], List[Dict]]
    ) -> None:
        """Add machine constraints with automatic strategy selection."""
        
        for m_id, tasks_on_machine in machine_tasks.items():
            n = len(tasks_on_machine)
            
            # Case 1: 0-1 tasks → no constraint
            if n <= 1:
                self._log(logging.DEBUG, f"Machine {m_id}: {n} tasks → NONE")
                continue
            
            # Category analysis (use effective type for job inheritance)
            categories = set(item['task'].get_effective_task_type() for item in tasks_on_machine)
            
            # Case 2: Single category → just NoOverlap (no setup needed)
            if len(categories) == 1:
                intervals = [item['interval'] for item in tasks_on_machine]
                model.AddNoOverlap(intervals)
                self._log(logging.DEBUG, f"Machine {m_id}: {n} tasks, {len(categories)} (1) category → NO_OVERLAP")
                continue

            # Case 3: Multiple categories with 0 setup times
            all_setup_zero = all(item['task'].setup_time == 0 for item in tasks_on_machine)
            if all_setup_zero:
                intervals = [item['interval'] for item in tasks_on_machine]
                model.AddNoOverlap(intervals)
                self._log(logging.DEBUG, f"Machine {m_id}: {n} tasks, {len(categories)} categories but all setup=0 → NO_OVERLAP")
                continue
            
            # Case 4-5: Multiple categories → Setup required
            if n > self.CIRCUIT_THRESHOLD:
                self._log(logging.DEBUG, f"Machine {m_id}: {n} tasks, {len(categories)} categories → CIRCUIT")
                self._add_setup_circuit(model, m_id, tasks_on_machine)
            else:
                self._log(logging.DEBUG, f"Machine {m_id}: {n} tasks, {len(categories)} categories → PAIRWISE")
                self._add_setup_pairwise(model, m_id, tasks_on_machine)

    def _add_setup_pairwise(
        self,
        model: cp_model.CpModel,
        m_id: Union[int, str],
        tasks_on_machine: List[Dict]
    ) -> None:
        """
        Pairwise disjunctive constraints with setup times.
        
        For each pair (i, j):
        - If same category: just disjunction (no setup)
        - If different category: disjunction with setup
        """
        n = len(tasks_on_machine)
        
        for i in range(n):
            for j in range(i + 1, n):
                item_i = tasks_on_machine[i]
                item_j = tasks_on_machine[j]
                
                task_i: Task = item_i['task']
                task_j: Task = item_j['task']
                
                pres_i = item_i['presence']
                pres_j = item_j['presence']
                end_i = item_i['end']
                end_j = item_j['end']
                start_i = item_i['start']
                start_j = item_j['start']
                
                # Calculate setup times (use effective type for job inheritance)
                same_category = (task_i.get_effective_task_type() == task_j.get_effective_task_type())
                setup_i = 0 if same_category else task_i.setup_time
                setup_j = 0 if same_category else task_j.setup_time
                
                # Ordering boolean: True = i before j
                i_before_j = model.NewBoolVar(f"ord_{m_id}_{task_i.id}_{task_j.id}")
                
                # DISJUNCTION with setup
                # If i before j: end[i] + setup[j] <= start[j]
                model.Add(end_i + setup_j <= start_j).OnlyEnforceIf([
                    pres_i, pres_j, i_before_j
                ])
                
                # If j before i: end[j] + setup[i] <= start[i]
                model.Add(end_j + setup_i <= start_i).OnlyEnforceIf([
                    pres_i, pres_j, i_before_j.Not()
                ])
                
                # SYMMETRY BREAKING for truly equivalent tasks
                # Only apply when tasks are completely interchangeable (no external deps)
                if same_category and task_i.setup_time == task_j.setup_time:
                    # Duration check (on this machine)
                    same_duration = (item_i['duration'] == item_j['duration'])
                    
                    # Due date check
                    same_due_date = (task_i.due_date == task_j.due_date)
                    
                    # Check if EITHER task has ANY predecessors (from any machine)
                    either_has_predecessors = (len(task_i.predecessors) > 0 or 
                                               len(task_j.predecessors) > 0)
                    
                    # ONLY for truly equivalent tasks with no external dependencies
                    if same_duration and same_due_date and not either_has_predecessors:
                        i_should_be_first = self._should_task_come_first(task_i, task_j)
                        if i_should_be_first is True:
                            model.AddImplication(pres_i, i_before_j).OnlyEnforceIf(pres_j)
                        elif i_should_be_first is False:
                            model.AddImplication(pres_i, i_before_j.Not()).OnlyEnforceIf(pres_j)


    def _add_setup_circuit(
        self,
        model: cp_model.CpModel,
        m_id: Union[int, str],
        tasks_on_machine: List[Dict]
    ) -> None:
        """Circuit-based sequencing with setup times."""
        
        n = len(tasks_on_machine)
        
        arcs = []
        arc_vars: Dict[tuple, cp_model.BoolVar] = {}
        
        # Create all arcs (including depot node 0)
        for i in range(n + 1):
            for j in range(n + 1):
                if i == j:
                    continue
                
                arc = model.NewBoolVar(f"arc_{m_id}_{i}_{j}")
                arcs.append((i, j, arc))
                arc_vars[(i, j)] = arc
        
        # Self-loops for optional tasks
        for idx, item in enumerate(tasks_on_machine):
            node = idx + 1
            self_loop = model.NewBoolVar(f"skip_{m_id}_{node}")
            arcs.append((node, node, self_loop))
            arc_vars[(node, node)] = self_loop
            
            # self_loop ↔ not present
            model.AddImplication(self_loop, item['presence'].Not())
            model.AddImplication(item['presence'].Not(), self_loop)
        
        # Depot self-loop (when no tasks on this machine)
        depot_skip = model.NewBoolVar(f"depot_skip_{m_id}")
        arcs.append((0, 0, depot_skip))
        arc_vars[(0, 0)] = depot_skip
        
        presence_vars = [item['presence'] for item in tasks_on_machine]
        any_present = model.NewBoolVar(f"any_present_{m_id}")
        model.AddMaxEquality(any_present, presence_vars)
        
        model.AddImplication(any_present, depot_skip.Not())
        model.AddImplication(any_present.Not(), depot_skip)
        
        # Circuit constraint
        model.AddCircuit(arcs)
        
        # NOTE: Removed Presence ↔ Arc constraints
        # Circuit + self-loop ↔ not present already ensures correct arc selection
        
        # Setup time constraints
        for i in range(1, n + 1):
            for j in range(1, n + 1):
                if i == j:
                    continue
                
                item_i = tasks_on_machine[i - 1]
                item_j = tasks_on_machine[j - 1]
                task_i: Task = item_i['task']
                task_j: Task = item_j['task']
                
                # Calculate setup (use effective type for job inheritance)
                if task_i.get_effective_task_type() == task_j.get_effective_task_type():
                    setup = 0
                else:
                    setup = task_j.setup_time
                
                arc = arc_vars.get((i, j))
                if arc is None:
                    continue
                
                # If arc is active, enforce setup
                model.Add(
                    item_i['end'] + setup <= item_j['start']
                ).OnlyEnforceIf(arc)
        
        # SYMMETRY BREAKING: Anchor depot to task that should come first
        # Only apply if tasks are truly interchangeable (no external dependencies)
        if n >= 2:
            first_task_idx = 0
            first_task = tasks_on_machine[0]['task']
            first_item = tasks_on_machine[0]
            
            found_equivalent = False
            
            for idx in range(1, n):
                candidate_item = tasks_on_machine[idx]
                candidate = candidate_item['task']
                
                # Check equivalence with current first
                same_duration = (first_item['duration'] == candidate_item['duration'])
                same_due_date = (first_task.due_date == candidate.due_date)
                same_category = (first_task.get_effective_task_type() == candidate.get_effective_task_type())
                same_setup = (first_task.setup_time == candidate.setup_time)
                
                # Check if EITHER task has ANY predecessors (from any machine)
                either_has_predecessors = (len(first_task.predecessors) > 0 or 
                                           len(candidate.predecessors) > 0)
                
                # Only compare if truly equivalent AND neither has external dependencies
                if (same_duration and same_due_date and same_category and 
                    same_setup and not either_has_predecessors):
                    found_equivalent = True
                    should_candidate_be_first = self._should_task_come_first(candidate, first_task)
                    if should_candidate_be_first is True:
                        first_task_idx = idx
                        first_task = candidate
                        first_item = candidate_item
            
            # ONLY apply anchor if equivalent tasks exist
            if found_equivalent:
                first_node = first_task_idx + 1
                first_pres = tasks_on_machine[first_task_idx]['presence']
                
                if (0, first_node) in arc_vars:
                    model.AddImplication(first_pres, arc_vars[(0, first_node)])

    def _extract_schedule(
        self,
        solver: cp_model.CpSolver,
        problem: SchedulingProblem,
        task_vars: Dict
    ) -> List[ScheduledTask]:
        """Extract schedule from solution."""
        schedule = []
        
        for task in problem.tasks:
            for m_id, vars_dict in task_vars[task.id].items():
                if solver.Value(vars_dict['presence']):
                    machine = problem.get_machine(m_id)
                    
                    schedule.append(ScheduledTask(
                        task=task,
                        machine=machine,
                        start_time=solver.Value(vars_dict['start']),
                        end_time=solver.Value(vars_dict['end']),
                        duration=solver.Value(vars_dict['end']) - solver.Value(vars_dict['start']),
                    ))
                    break
        
        schedule.sort(key=lambda x: (x.machine_id, x.start_time))
        return schedule

    def _status_to_string(self, status: int) -> str:
        """Convert CP-SAT status to string."""
        return {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "UNKNOWN",
        }.get(status, "UNKNOWN")

    def _add_symmetry_breaking(
        self,
        model: cp_model.CpModel,
        problem: SchedulingProblem,
        task_vars: Dict
    ) -> None:
        """
        Symmetry breaking hints for identical machines.
        
        Strategy: Suggest loading M1 before M2 for identical tasks.
        Uses hints (not hard constraints) to avoid suboptimal solutions.
        """
        # Group machines by capabilities (currently all equal, future: add other features)
        machine_groups: Dict[tuple, List] = {}
        for m in problem.machines.values():
            # All machines are currently equal (no speed_factor)
            # Future: group by other capabilities
            key = ()  # All in same group
            if key not in machine_groups:
                machine_groups[key] = []
            machine_groups[key].append(m.id)
        
        for group_key, machine_ids in machine_groups.items():
            # Only apply if 2+ identical machines
            if len(machine_ids) <= 1:
                continue
            
            # Skip small problems (overhead > benefit)
            jobs_per_machine = len(problem.tasks) / len(machine_ids)
            if jobs_per_machine < 5:
                continue
            
            machine_ids_sorted = sorted(machine_ids, key=str)
            
            # For identical tasks, hint preference for first machine in sorted order
            for task in problem.tasks:
                if task.id in task_vars:
                    # Check if task can run on multiple machines in this group
                    available_in_group = [m for m in machine_ids_sorted if m in task_vars[task.id]]
                    
                    if len(available_in_group) >= 2:
                        # Check if duration is same on all (truly identical)
                        first_duration = task_vars[task.id][available_in_group[0]]['duration']
                        all_same_duration = all(
                            task_vars[task.id][m]['duration'] == first_duration 
                            for m in available_in_group
                        )
                        
                        if all_same_duration:
                            # Hint: prefer first machine in sorted order
                            preferred = available_in_group[0]
                            model.AddHint(task_vars[task.id][preferred]['presence'], 1)

    def _should_task_come_first(self, task_i: Task, task_j: Task) -> Optional[bool]:
        """
        Determine if task_i should come before task_j for symmetry breaking.
        
        Priority:
        1. Earlier due date comes first (for tardiness optimization)
        2. Smaller ID as tiebreaker
        
        Returns:
            True: task_i should come first
            False: task_j should come first
            None: Tasks are truly equivalent (no symmetry breaking)
        """
        # Compare due dates
        dd_i = task_i.due_date
        dd_j = task_j.due_date
        
        if dd_i is not None and dd_j is not None:
            if dd_i < dd_j:
                return True  # i has earlier due date
            elif dd_j < dd_i:
                return False  # j has earlier due date
            # Due dates equal, fall through to ID comparison
        elif dd_i is not None and dd_j is None:
            return True  # i has due date, j doesn't → i first
        elif dd_j is not None and dd_i is None:
            return False  # j has due date, i doesn't → j first
        # Both None or equal, fall through to ID comparison
        
        # Tiebreaker: smaller ID first
        if str(task_i.id) < str(task_j.id):
            return True
        elif str(task_j.id) < str(task_i.id):
            return False
        
        # Truly equivalent
        return None
