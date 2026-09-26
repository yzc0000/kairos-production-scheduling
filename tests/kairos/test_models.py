"""
Tests for domain models: Task, Job, Machine, SchedulingProblem, SolutionResult
"""

import pytest
from kairos.domain.models import (
    Task, Job, Machine, SchedulingProblem, ScheduledTask,
    SolutionResult, ProblemFeature, TaskType
)


class TestTask:
    """Tests for Task model."""
    
    def test_task_creation(self):
        """Test basic task creation."""
        task = Task(id=1, name="Test Task")
        assert task.id == 1
        assert task.name == "Test Task"
        assert task.task_type is None
        assert task.setup_time == 0
        assert task.predecessors == []
        assert task.alternatives == {}
    
    def test_task_with_type(self):
        """Test task with task_type."""
        task = Task(id=1, name="Weld", task_type="Welding", setup_time=25)
        assert task.task_type == "Welding"
        assert task.setup_time == 25
    
    def test_add_alternative(self):
        """Test adding machine alternatives."""
        task = Task(id=1, name="Test")
        task.add_alternative(1, 100)
        task.add_alternative(2, 80)
        
        assert len(task.alternatives) == 2
        assert task.alternatives[1] == 100
        assert task.alternatives[2] == 80
    
    def test_add_predecessor(self):
        """Test adding predecessor tasks."""
        task1 = Task(id=1, name="First")
        task2 = Task(id=2, name="Second")
        
        task2.add_predecessor(task1)
        
        assert len(task2.predecessors) == 1
        assert task2.predecessors[0] == task1
    
    def test_add_duplicate_predecessor(self):
        """Test that duplicate predecessors are not added."""
        task1 = Task(id=1, name="First")
        task2 = Task(id=2, name="Second")
        
        task2.add_predecessor(task1)
        task2.add_predecessor(task1)  # Duplicate
        
        assert len(task2.predecessors) == 1
    
    def test_get_effective_task_type_own(self):
        """Test effective task type returns own type."""
        task = Task(id=1, name="Test", task_type="Welding")
        assert task.get_effective_task_type() == "Welding"
    
    def test_get_effective_task_type_from_job(self):
        """Test effective task type inherits from job."""
        job = Job(id="J1", name="Job1", task_type="Painting")
        task = Task(id=1, name="Test")
        job.add_task(task)
        
        assert task.get_effective_task_type() == "Painting"
    
    def test_get_effective_task_type_fallback(self):
        """Test effective task type falls back to name."""
        task = Task(id=1, name="MyTask")
        assert task.get_effective_task_type() == "MyTask"
    
    def test_due_date_from_job(self):
        """Test task inherits due_date from job."""
        job = Job(id="J1", name="Job1", due_date=500)
        task = Task(id=1, name="Test")
        job.add_task(task)
        
        assert task.due_date == 500
    
    def test_priority_from_job(self):
        """Test task inherits priority from job."""
        job = Job(id="J1", name="Job1", priority=3)
        task = Task(id=1, name="Test")
        job.add_task(task)
        
        assert task.priority == 3


class TestJob:
    """Tests for Job model."""
    
    def test_job_creation(self):
        """Test basic job creation."""
        job = Job(id="J1", name="Product A")
        assert job.id == "J1"
        assert job.name == "Product A"
        assert job.due_date is None
        assert job.priority == 1
        assert job.tasks == []
    
    def test_job_with_due_date(self):
        """Test job with due date and priority."""
        job = Job(id=1, name="Urgent", due_date=200, priority=5)
        assert job.due_date == 200
        assert job.priority == 5
    
    def test_add_task(self):
        """Test adding task to job."""
        job = Job(id="J1", name="Job")
        task = Task(id=1, name="Task1")
        
        job.add_task(task)
        
        assert len(job.tasks) == 1
        assert task.job == job
    
    def test_add_duplicate_task(self):
        """Test that duplicate tasks are not added."""
        job = Job(id="J1", name="Job")
        task = Task(id=1, name="Task1")
        
        job.add_task(task)
        job.add_task(task)  # Duplicate
        
        assert len(job.tasks) == 1


class TestMachine:
    """Tests for Machine model."""
    
    def test_machine_creation(self):
        """Test basic machine creation."""
        machine = Machine(id=1, name="CNC")
        assert machine.id == 1
        assert machine.name == "CNC"
        assert machine.hourly_cost == 0.0
    
    def test_machine_with_cost(self):
        """Test machine with hourly cost."""
        machine = Machine(id=1, name="CNC", hourly_cost=100.0)
        assert machine.hourly_cost == 100.0
    
    def test_machine_equality(self):
        """Test machine equality by id."""
        m1 = Machine(id=1, name="CNC")
        m2 = Machine(id=1, name="Different")
        m3 = Machine(id=2, name="CNC")
        assert m1 == m2
        assert m1 != m3


class TestSchedulingProblem:
    """Tests for SchedulingProblem model."""
    
    def test_empty_problem(self):
        """Test empty problem creation."""
        problem = SchedulingProblem(name="Test")
        assert problem.name == "Test"
        assert len(problem.tasks) == 0
        assert len(problem.machines) == 0
        assert len(problem.jobs) == 0
    
    def test_add_machine(self):
        """Test adding machine."""
        problem = SchedulingProblem()
        machine = Machine(id=1, name="M1")
        problem.add_machine(machine)
        
        assert len(problem.machines) == 1
        assert problem.get_machine(1) == machine
    
    def test_add_task(self):
        """Test adding standalone task."""
        problem = SchedulingProblem()
        task = Task(id=1, name="T1")
        problem.add_task(task)
        
        assert len(problem.tasks) == 1
    
    def test_add_job(self):
        """Test adding job with tasks."""
        problem = SchedulingProblem()
        job = Job(id="J1", name="Job")
        task = Task(id=1, name="T1")
        job.add_task(task)
        
        problem.add_job(job)
        
        assert len(problem.jobs) == 1
        assert len(problem.tasks) == 1  # Task added from job
    
    def test_get_features_multi_machine(self):
        """Test feature detection: multi machine."""
        problem = SchedulingProblem()
        task = Task(id=1, name="T1")
        task.add_alternative(1, 100)
        task.add_alternative(2, 80)
        problem.add_task(task)
        
        features = problem.get_features()
        assert ProblemFeature.MULTI_MACHINE in features
    
    def test_get_features_precedence(self):
        """Test feature detection: precedence."""
        problem = SchedulingProblem()
        t1 = Task(id=1, name="T1")
        t2 = Task(id=2, name="T2")
        t2.add_predecessor(t1)
        problem.add_task(t1)
        problem.add_task(t2)
        
        features = problem.get_features()
        assert ProblemFeature.PRECEDENCE in features
    
    def test_get_features_setup_times(self):
        """Test feature detection: setup times."""
        problem = SchedulingProblem()
        task = Task(id=1, name="T1", setup_time=25)
        problem.add_task(task)
        
        features = problem.get_features()
        assert ProblemFeature.SETUP_TIMES in features


class TestSolutionResult:
    """Tests for SolutionResult model."""
    
    def test_is_success_optimal(self):
        """Test is_success for OPTIMAL."""
        result = SolutionResult(status="OPTIMAL")
        assert result.is_success is True
    
    def test_is_success_feasible(self):
        """Test is_success for FEASIBLE."""
        result = SolutionResult(status="FEASIBLE")
        assert result.is_success is True
    
    def test_is_success_infeasible(self):
        """Test is_success for INFEASIBLE."""
        result = SolutionResult(status="INFEASIBLE")
        assert result.is_success is False
    
    def test_calculate_metrics(self):
        """Test metrics calculation."""
        # Create scheduled tasks
        task = Task(id=1, name="T1")
        machine = Machine(id=1, name="M1")
        scheduled = ScheduledTask(
            task=task,
            machine=machine,
            start_time=0,
            end_time=100,
            duration=100
        )
        
        job = Job(id="J1", name="Job", due_date=80, priority=2)
        job.add_task(task)
        
        result = SolutionResult(status="OPTIMAL", schedule=[scheduled])
        result.calculate_metrics([job])
        
        assert result.makespan == 100
        assert result.weighted_tardiness == 40  # (100 - 80) * 2
        assert result.total_completion_time == 100
