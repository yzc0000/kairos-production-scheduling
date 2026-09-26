"""
Tests for ExcelDataLoader

Uses shared fixtures from conftest.py
"""

import pytest
from kairos.data.excel_loader import ExcelDataLoader


class TestExcelDataLoader:
    """Tests for ExcelDataLoader."""
    
    @pytest.fixture
    def loader(self):
        """Create ExcelDataLoader instance."""
        return ExcelDataLoader()
    
    def test_load_machines(self, loader, simple_excel_file):
        """Test loading machines from Excel."""
        problem = loader.load_problem(simple_excel_file)
        
        assert len(problem.machines) == 2
        assert problem.get_machine(1).name == "M1"
        assert problem.get_machine(2).name == "M2"
    
    def test_load_tasks(self, loader, simple_excel_file):
        """Test loading tasks from Excel."""
        problem = loader.load_problem(simple_excel_file)
        
        assert len(problem.tasks) == 2
        
        task_a = next(t for t in problem.tasks if t.id == 101)
        assert task_a.name == "Task_A"
        assert task_a.task_type == "Welding"
        assert task_a.setup_time == 25
    
    def test_load_alternatives(self, loader, simple_excel_file):
        """Test loading machine alternatives."""
        problem = loader.load_problem(simple_excel_file)
        
        task_a = next(t for t in problem.tasks if t.id == 101)
        assert len(task_a.alternatives) == 2
        assert task_a.alternatives[1] == 100
        assert task_a.alternatives[2] == 80
    
    def test_load_predecessors(self, loader, simple_excel_file):
        """Test loading predecessor relationships."""
        problem = loader.load_problem(simple_excel_file)
        
        task_b = next(t for t in problem.tasks if t.id == 102)
        assert len(task_b.predecessors) == 1
        assert task_b.predecessors[0].id == 101
    
    def test_load_jobs(self, loader, excel_with_jobs):
        """Test loading jobs from Excel."""
        problem = loader.load_problem(excel_with_jobs)
        
        assert len(problem.jobs) == 2
        
        job1 = next(j for j in problem.jobs if j.id == "JOB_1")
        assert job1.name == "Product A"
        assert job1.due_date == 500
        assert job1.priority == 2
        assert job1.task_type == "Assembly"
    
    def test_job_task_association(self, loader, excel_with_jobs):
        """Test that tasks are correctly associated with jobs."""
        problem = loader.load_problem(excel_with_jobs)
        
        job1 = next(j for j in problem.jobs if j.id == "JOB_1")
        assert len(job1.tasks) == 2
        
        # All job tasks should be in problem.tasks
        assert len(problem.tasks) == 3
        
        # All tasks in job1 should have job reference
        for task in job1.tasks:
            assert task.job == job1
    
    def test_problem_name(self, loader, simple_excel_file):
        """Test custom problem name."""
        problem = loader.load_problem(simple_excel_file, problem_name="My Schedule")
        assert problem.name == "My Schedule"
    
    def test_parse_id_integer(self, loader):
        """Test parsing integer IDs."""
        assert loader._parse_id(123) == 123
        assert loader._parse_id("456") == 456
        assert loader._parse_id(1.0) == 1
    
    def test_parse_id_string(self, loader):
        """Test parsing string IDs."""
        assert loader._parse_id("JOB_1") == "JOB_1"
        assert loader._parse_id("  ABC  ") == "ABC"
    
    def test_parse_optional_int(self, loader):
        """Test parsing optional integers."""
        assert loader._parse_optional_int(100) == 100
        assert loader._parse_optional_int(None) is None
        assert loader._parse_optional_int(float('nan')) is None
    
    def test_parse_task_type(self, loader):
        """Test parsing task types."""
        assert loader._parse_task_type(1) == 1
        assert loader._parse_task_type("Welding") == "Welding"
        assert loader._parse_task_type("1.0") == 1
