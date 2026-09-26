"""
Domain models for industrial job shop scheduling problems.

This module contains all data models following clean architecture principles.
All models are in a single file to avoid circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, Flag, auto
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from kairos.solvers.factory import ObjectiveType


class ProblemFeature(Flag):
    """
    Flags representing problem characteristics.
    
    Used by solvers to determine if they can handle a specific problem.
    A solver declares its supported features, and problems are analyzed
    to determine their required features.
    """
    NONE = 0
    MULTI_MACHINE = auto()           # Tasks can run on multiple machines
    SETUP_TIMES = auto()             # Sequence-dependent setup times exist
    PRECEDENCE = auto()              # Tasks have predecessor constraints
    DUE_DATES = auto()               # Tasks have deadlines
    MACHINE_SPECIFIC_SETUP = auto()  # Different setup matrices per machine
    VARIABLE_SPEED = auto()          # Machines have different speed factors
    PREEMPTION = auto()              # Tasks can be interrupted and resumed
    RELEASE_TIME = auto()            # Tasks have release times (not available at t=0)


class TaskType(IntEnum):
    """
    Enumeration for task types/job families.
    
    Tasks with the same TaskType typically have 0 setup time between them.
    Example usage:
        class MyTaskTypes(TaskType):
            WELDING = 0
            PAINTING = 1
            ASSEMBLY = 2
    """
    DEFAULT = 0


@dataclass
class Task:
    """
    Represents an operation/task in the scheduling problem.
    
    Attributes:
        id: Unique identifier for the task
        name: Human-readable name
        task_type: Job family/category identifier for setup time logic
        setup_time: Fixed setup time when preceded by a different task_type
                   (0 setup if preceded by same task_type)
        predecessors: Tasks that must complete before this one starts
        alternatives: Dict mapping machine_id to processing duration
        job: Reference to the parent job (set automatically when added to a job)
        release_time: When task becomes available (default 0)
    """
    id: Union[int, str]
    name: str
    task_type: Optional[Union[TaskType, int, str]] = None  # Task's own type (can be None)
    setup_time: int = 0
    predecessors: List[Task] = field(default_factory=list)
    alternatives: Dict[Union[int, str], int] = field(default_factory=dict)
    job: Optional[Job] = field(default=None, repr=False)
    release_time: int = 0
    
    def get_effective_task_type(self) -> Union[TaskType, int, str]:
        """
        Get effective task type with fallback logic:
        1. Task's own task_type if specified
        2. Job's task_type if task is in a job
        3. Task's name as fallback
        """
        if self.task_type is not None:
            return self.task_type
        if self.job and self.job.task_type is not None:
            return self.job.task_type
        return self.name  # Fallback to task name
    
    @property
    def due_date(self) -> Optional[int]:
        """Get due date from parent job."""
        return self.job.due_date if self.job else None
    
    @property
    def priority(self) -> int:
        """Get priority from parent job."""
        return self.job.priority if self.job else 1
    
    def add_predecessor(self, task: Task) -> None:
        """Add a task that must complete before this one.
        
        Args:
            task (Task): The task that must complete before this one.
        """
        if task not in self.predecessors:
            self.predecessors.append(task)
    
    def add_alternative(self, machine_id: Union[int, str], duration: int) -> None:
        """
    Add a machine alternative with its processing time.

    Args:
        machine_id (int | str): ID of the machine. Can be integer or string.
        duration (int): Processing time in minutes for the machine.
        """
        self.alternatives[machine_id] = duration
    
    def __hash__(self) -> int:
        return hash(self.id)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Task):
            return False
        return self.id == other.id


@dataclass
class Job:
    """
    Represents a job containing multiple tasks.
    
    A job groups related tasks (operations) that must be completed together.
    Due dates and priorities are at the job level, not task level.
    
    Attributes:
        id: Unique identifier for the job
        name: Human-readable name
        due_date: Optional deadline in minutes
        priority: Job priority (higher = more important)
        task_type: Default task type for all tasks in this job (e.g., "Wheel", "Engine")
        tasks: List of tasks belonging to this job
    """
    id: Union[int, str]
    name: str
    due_date: Optional[int] = None
    priority: int = 1
    task_type: Optional[Union[TaskType, int, str]] = None  # Inherited by tasks
    tasks: List[Task] = field(default_factory=list)
    
    def add_task(self, task: Task) -> None:
        """Add a task to this job.

        Args:
            task (Task): The task to add to this job.
        """
        task.job = self  # Set back-reference
        if task not in self.tasks:
            self.tasks.append(task)
    
    def __hash__(self) -> int:
        return hash(self.id)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Job):
            return False
        return self.id == other.id


@dataclass
class Machine:
    """
    Represents a machine/resource in the scheduling problem.
    
    Attributes:
        id: Unique identifier
        name: Human-readable name
        hourly_cost: Cost per hour of operation
    """
    id: Union[int, str]
    name: str
    hourly_cost: float = 0.0
    
    def __hash__(self) -> int:
        return hash(self.id)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Machine):
            return False
        return self.id == other.id


@dataclass
class SchedulingProblem:
    """
    Complete definition of a job shop scheduling problem.
    
    Attributes:
        name: Problem name/identifier
        jobs: List of all jobs (each job contains tasks)
        tasks: List of all tasks to schedule (auto-populated from jobs)
        machines: Dict mapping machine_id to Machine objects
        num_task_types: Number of distinct task types
        task_type_names: User-defined mapping of task_type -> name (e.g., {0: "Welding", 1: "Painting"})
        preemption_allowed: If True, tasks can be interrupted and resumed
    """
    name: str = "Scheduling Problem"
    jobs: List[Job] = field(default_factory=list)
    tasks: List[Task] = field(default_factory=list)
    machines: Dict[Union[int, str], Machine] = field(default_factory=dict)
    num_task_types: int = 0
    task_type_names: Dict[int, str] = field(default_factory=dict)
    preemption_allowed: bool = False
    
    def enable_preemption(self) -> None:
        """Enable preemption - tasks can be interrupted and resumed."""
        self.preemption_allowed = True
    
    def set_task_type_names(self, names: Dict[int, str]) -> None:
        """
        Set user-defined names for task types.
        
        Args:
            names: Dict mapping task_type (int) to name (str)
                   e.g., {0: "Welding", 1: "Painting", 2: "Assembly"}
        """
        self.task_type_names = names
    
    def get_task_type_name(self, task_type: Union[int, str]) -> str:
        """Get human-readable name for a task type.

        Args:
            task_type (Union[int, str]): The task type to get the name for.

        Returns:
            str: The human-readable name for the task type.
        """
        # If task_type is already a string, return it as the name
        if isinstance(task_type, str):
            return task_type
        # Otherwise look up in mapping or return default
        return self.task_type_names.get(int(task_type), f"Type {task_type}")
    
    def add_job(self, job: Job) -> None:
        """Add a job and its tasks to the problem."""
        if job not in self.jobs:
            self.jobs.append(job)
        # Also add all tasks from the job
        for task in job.tasks:
            if task not in self.tasks:
                self.tasks.append(task)
                self._update_task_types(task)
    
    def add_task(self, task: Task) -> None:
        """Add a standalone task to the problem (without a job).

        Args:
            task (Task): The standalone task to add to the problem.
        """
        self.tasks.append(task)
        self._update_task_types(task)
    
    def _update_task_types(self, task: Task) -> None:
        """Update num_task_types based on task.

        Args:
            task (Task): The task to update num_task_types based on.
        """
        # Only count numeric task types
        if isinstance(task.task_type, (int, TaskType)):
            task_type_value = int(task.task_type)
            if task_type_value >= self.num_task_types:
                self.num_task_types = task_type_value + 1
    
    def add_machine(self, machine: Machine) -> None:
        """Add a machine to the problem.

        Args:
            machine (Machine): The machine to add to the problem.
            
        Warning:
            If a machine with the same ID already exists, it will be overwritten.
        """
        if machine.id in self.machines:
            import warnings
            warnings.warn(
                f"Machine with ID {machine.id} already exists. "
                f"Overwriting '{self.machines[machine.id].name}' with '{machine.name}'",
                UserWarning
            )
        self.machines[machine.id] = machine
    
    def get_machine(self, machine_id: Union[int, str]) -> Optional[Machine]:
        """Retrieve a machine by its ID.

        Args:
            machine_id (Union[int, str]): The ID of the machine to retrieve.

        Returns:
            Optional[Machine]: The machine with the specified ID, or None if not found.
        """
        return self.machines.get(machine_id)
    
    def get_features(self) -> ProblemFeature:
        """
        Analyze the problem and return its feature flags.
        
        This is used by solvers to determine compatibility.
        """
        features = ProblemFeature.NONE
        
        # Check for multi-machine alternatives
        for task in self.tasks:
            if len(task.alternatives) > 1:
                features |= ProblemFeature.MULTI_MACHINE
                break
        
        # Check for precedence constraints
        for task in self.tasks:
            if task.predecessors:
                features |= ProblemFeature.PRECEDENCE
                break
        
        # Check for due dates
        for task in self.tasks:
            if task.due_date is not None:
                features |= ProblemFeature.DUE_DATES
                break
        
        # Check for setup times (now uses Task.setup_time)
        for task in self.tasks:
            if task.setup_time > 0:
                features |= ProblemFeature.SETUP_TIMES
                break
        
        # Check for variable speed (different durations on different machines)
        for task in self.tasks:
            if len(task.alternatives) > 1:
                durations = list(task.alternatives.values())
                if len(set(durations)) > 1:  # Different durations exist
                    features |= ProblemFeature.VARIABLE_SPEED
                    break
        
        # Check for preemption allowed
        if self.preemption_allowed:
            features |= ProblemFeature.PREEMPTION
        
        # Check for release times
        for task in self.tasks:
            if task.release_time > 0:
                features |= ProblemFeature.RELEASE_TIME
                break
        
        return features


@dataclass
class ScheduledTask:
    """
    A single task in the solution schedule.
    
    Memory-optimized: Stores references to Task/Machine objects
    instead of copying their fields. Properties provide backwards
    compatibility with the old field-based interface.
    
    Core scheduling data (stored directly):
        - task: Reference to the original Task object
        - machine: Reference to the assigned Machine object
        - start_time: When the task starts
        - end_time: When the task ends
        - duration: Actual processing duration
    """
    task: Task
    machine: Machine
    start_time: int
    end_time: int
    duration: int
    
    # Properties for backwards compatibility
    @property
    def task_id(self) -> Union[int, str]:
        return self.task.id
    
    @property
    def task_name(self) -> str:
        return self.task.name
    
    @property
    def machine_id(self) -> Union[int, str]:
        return self.machine.id
    
    @property
    def machine_name(self) -> str:
        return self.machine.name
    
    @property
    def setup_time(self) -> int:
        return self.task.setup_time
    
    @property
    def task_type(self) -> Union[TaskType, int, str]:
        return self.task.get_effective_task_type()
    
    @property
    def task_type_name(self) -> str:
        """Human-readable type name (same as task_type for string types)."""
        tt = self.task.get_effective_task_type()
        return str(tt) if tt is not None else ""
    
    @property
    def job(self) -> Optional[Job]:
        """Access parent Job via task reference."""
        return self.task.job
    
    @property
    def job_id(self) -> Optional[Union[int, str]]:
        return self.task.job.id if self.task.job else None
    
    @property
    def job_name(self) -> str:
        return self.task.job.name if self.task.job else "Standalone"
    


@dataclass
class SolutionResult:
    """
    Result of solving a scheduling problem.
    
    Attributes:
        status: Solver status ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "INCOMPATIBLE", etc.)
        objective_type: Objective type ("Makespan", "Total Weighted Tardiness", etc.)
        objective_value: The objective function value (depends on objective type)
        schedule: List of scheduled tasks
        message: Optional message (e.g., error description)
        solve_time_seconds: Time taken to solve
        makespan: Maximum completion time across all jobs
        weighted_tardiness: Sum of (tardiness * priority) for all jobs
        total_completion_time: Sum of all job completion times
    """
    status: str
    objective_type: Optional['ObjectiveType'] = None
    objective_value: Optional[int] = None
    schedule: List[ScheduledTask] = field(default_factory=list)
    message: str = ""
    solve_time_seconds: float = 0.0
    gap_percentage: Optional[float] = None  # 0.0 = optimal, None = not computed
    
    # Metrics (calculated regardless of objective)
    makespan: Optional[int] = None
    weighted_tardiness: Optional[int] = None
    total_completion_time: Optional[int] = None
    
    @property
    def is_success(self) -> bool:
        """Check if the solution is valid."""
        return self.status in ("OPTIMAL", "FEASIBLE")
    
    def to_dict_list(self) -> List[Dict]:
        """Convert schedule to list of dictionaries (for DataFrame conversion)."""
        return [
            {
                "task_id": s.task_id,
                "task_name": s.task_name,
                "machine_id": s.machine_id,
                "machine_name": s.machine_name,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "duration": s.duration,
                "task_type": s.task_type if isinstance(s.task_type, (int, str)) else int(s.task_type),
            }
            for s in self.schedule
        ]
    
    def calculate_metrics(self, jobs: List['Job']) -> None:
        """
        Calculate all metrics from the schedule.
        
        This method can be called by any solver after extracting the schedule.
        Sets makespan, weighted_tardiness, and total_completion_time.
        
        Args:
            jobs: List of jobs to calculate metrics for
        """
        if not self.schedule:
            return
        
        # Build task_id -> end_time mapping (max end_time for multi-segment tasks)
        task_end_times: Dict[Union[int, str], float] = {}
        for s in self.schedule:
            if s.task_id not in task_end_times:
                task_end_times[s.task_id] = s.end_time
            else:
                task_end_times[s.task_id] = max(task_end_times[s.task_id], s.end_time)
        
        # Calculate job completion times (max end time of tasks in each job)
        job_completion_times = {}
        tasks_in_jobs = set()
        
        for job in jobs:
            task_ends = [task_end_times.get(t.id, 0) for t in job.tasks if t.id in task_end_times]
            if task_ends:
                job_completion_times[job.id] = max(task_ends)
            for t in job.tasks:
                tasks_in_jobs.add(t.id)
        
        # Standalone tasks (not in any job)
        standalone_ends = [end for tid, end in task_end_times.items() if tid not in tasks_in_jobs]
        
        # Makespan = max of all completions
        all_completions = list(job_completion_times.values()) + standalone_ends
        self.makespan = max(all_completions) if all_completions else 0
        
        # Weighted tardiness (only jobs with due dates)
        self.weighted_tardiness = 0
        for job in jobs:
            if job.id in job_completion_times and job.due_date is not None:
                completion = job_completion_times[job.id]
                tardiness = max(0, completion - job.due_date)
                self.weighted_tardiness += tardiness * job.priority
        
        # Total completion time (jobs + standalone tasks)
        job_total = sum(job_completion_times.values()) if job_completion_times else 0
        standalone_total = sum(standalone_ends) if standalone_ends else 0
        self.total_completion_time = job_total + standalone_total
