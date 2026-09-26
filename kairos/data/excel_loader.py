"""
Excel data loader for scheduling problems.

Loads problem data from Excel files with sheets:
- Machines: id, name, hourly_cost
- Jobs: id, name, due_date, priority, task_type
- Tasks: id, name, job_id, task_type, setup_time, alternatives, predecessors
"""

from typing import Dict, Optional, Union

import pandas as pd

from kairos.domain.models import Job, Machine, SchedulingProblem, Task


class ExcelDataLoader:
    """
    Load scheduling problems from Excel files.
    
    Expected Excel structure:
    
    Sheet "Machines":
        | id | name | hourly_cost |
        |----|------|-------------|
        | 1  | CNC  | 100         |
    
    Sheet "Jobs" (optional):
        | id    | name      | due_date | priority | task_type |
        |-------|-----------|----------|----------|-----------|
        | JOB_1 | Product A | 500      | 2        | Welding   |
    
    Sheet "Tasks":
        | id  | name   | job_id | task_type | setup_time | release_time | alternatives | predecessors |
        |-----|--------|--------|-----------|------------|--------------|--------------|
        | 101 | Part_A | JOB_1  | Welding   | 25         | 0            | 1:100,2:80   | 102,103      |
    
    Notes:
        - job_id: Reference to a job in Jobs sheet (optional - tasks without job_id are standalone)
        - task_type: Can be int or string. If not specified, inherits from job
        - setup_time: Setup duration when preceded by different task_type
        - release_time: When task becomes available (default 0)
        - alternatives: "machine_id:duration" pairs separated by commas
        - predecessors: Task IDs separated by commas
    """
    
    def load_problem(self, file_path: str, problem_name: str = "Loaded Problem") -> SchedulingProblem:
        """
        Load a scheduling problem from an Excel file.
        
        Args:
            file_path: Path to the Excel file.
            problem_name: Name for the created problem.
            
        Returns:
            A SchedulingProblem instance.
        """
        problem = SchedulingProblem(name=problem_name)
        
        # Load machines (required)
        machines_df = pd.read_excel(file_path, sheet_name="Machines")
        self._load_machines(problem, machines_df)
        
        # Load jobs (optional)
        job_lookup = {}
        try:
            jobs_df = pd.read_excel(file_path, sheet_name="Jobs")
            job_lookup = self._load_jobs(problem, jobs_df)
        except ValueError:
            pass  # Jobs sheet doesn't exist - all tasks will be standalone
        
        # Load tasks (required)
        tasks_df = pd.read_excel(file_path, sheet_name="Tasks")
        task_lookup = self._load_tasks(problem, tasks_df, job_lookup)
        
        # Link predecessors (second pass)
        self._link_predecessors(task_lookup, tasks_df)
        
        # Ensure all job tasks are also in problem.tasks
        for job in problem.jobs:
            for task in job.tasks:
                if task not in problem.tasks:
                    problem.tasks.append(task)
        
        return problem
    
    def _load_machines(self, problem: SchedulingProblem, df: pd.DataFrame) -> None:
        """Load machines from DataFrame."""
        for _, row in df.iterrows():
            machine = Machine(
                id=self._parse_id(row["id"]),
                name=str(row["name"]),
                hourly_cost=self._parse_float_with_default(row.get("hourly_cost"), 0.0),
            )
            problem.add_machine(machine)
    
    def _load_jobs(self, problem: SchedulingProblem, df: pd.DataFrame) -> Dict[Union[int, str], Job]:
        """Load jobs from DataFrame, return lookup dict."""
        job_lookup = {}
        
        for _, row in df.iterrows():
            job_id = self._parse_id(row["id"])
            
            # Parse task_type (can be int or string)
            task_type = None
            if "task_type" in row and pd.notna(row.get("task_type")):
                task_type = self._parse_task_type(row["task_type"])
            
            job = Job(
                id=job_id,
                name=str(row.get("name", f"Job_{job_id}")),
                due_date=self._parse_optional_int(row.get("due_date")),
                priority=int(row.get("priority", 1)),
                task_type=task_type,
            )
            
            problem.add_job(job)
            job_lookup[job_id] = job
        
        return job_lookup
    
    def _load_tasks(
        self, 
        problem: SchedulingProblem, 
        df: pd.DataFrame,
        job_lookup: Dict[Union[int, str], Job]
    ) -> Dict[Union[int, str], Task]:
        """Load tasks from DataFrame, return lookup dict."""
        task_lookup = {}
        
        for _, row in df.iterrows():
            task_id = self._parse_id(row["id"])
            
            # Parse task_type (can be int or string)
            task_type = None
            if "task_type" in row and pd.notna(row.get("task_type")):
                task_type = self._parse_task_type(row["task_type"])
            
            task = Task(
                id=task_id,
                name=str(row["name"]),
                task_type=task_type,
                setup_time=self._parse_int_with_default(row.get("setup_time"), 0),
                release_time=self._parse_int_with_default(row.get("release_time"), 0),
            )
            
            # Parse alternatives (format: "1:100,2:80")
            alternatives_str = str(row.get("alternatives", ""))
            if alternatives_str and alternatives_str != "nan":
                for alt in alternatives_str.split(","):
                    alt = alt.strip()
                    if ":" in alt:
                        machine_id_str, duration_str = alt.split(":")
                        machine_id = self._parse_id(machine_id_str.strip())
                        duration = int(duration_str.strip())
                        task.add_alternative(machine_id, duration)
            
            # Link to job if job_id specified
            job_id_raw = row.get("job_id")
            if pd.notna(job_id_raw):
                job_id = self._parse_id(job_id_raw)
                job = job_lookup.get(job_id)
                if job:
                    job.add_task(task)  # This also sets task.job
                else:
                    # Job not found, add as standalone
                    problem.add_task(task)
            else:
                # No job_id, add as standalone
                problem.add_task(task)
            
            task_lookup[task_id] = task
        
        return task_lookup
    
    def _link_predecessors(self, task_lookup: Dict, df: pd.DataFrame) -> None:
        """Link predecessor tasks (second pass)."""
        for _, row in df.iterrows():
            task_id = self._parse_id(row["id"])
            task = task_lookup.get(task_id)
            
            if not task:
                continue
            
            predecessors_str = str(row.get("predecessors", ""))
            if predecessors_str and predecessors_str != "nan":
                for pred_id_str in predecessors_str.split(","):
                    pred_id = self._parse_id(pred_id_str.strip())
                    pred_task = task_lookup.get(pred_id)
                    if pred_task:
                        task.add_predecessor(pred_task)
    
    def _parse_id(self, value) -> Union[int, str]:
        """Parse an ID value as int if possible, otherwise string."""
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return str(value).strip()
    
    def _parse_task_type(self, value) -> Union[int, str]:
        """Parse task_type as int if numeric, otherwise string."""
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return str(value).strip()
    
    def _parse_optional_int(self, value) -> Optional[int]:
        """Parse an optional integer value."""
        if pd.isna(value):
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
    
    def _parse_int_with_default(self, value, default: int = 0) -> int:
        """Parse an integer value with a default if NaN or invalid."""
        if pd.isna(value):
            return default
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default

    def _parse_float_with_default(self, value, default: float = 0.0) -> float:
        """Parse a float value with a default if NaN or invalid."""
        if pd.isna(value):
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
