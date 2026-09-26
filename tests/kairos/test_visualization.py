"""
Tests for visualization: GanttVisualizer, DependencyGraphVisualizer

Uses shared fixtures from conftest.py
"""

import pytest
from kairos.visualization.gantt import GanttVisualizer
from kairos.visualization.dependency_graph import DependencyGraphVisualizer
from kairos.domain.models import Job


class TestGanttVisualizer:
    """Tests for GanttVisualizer."""
    
    @pytest.fixture
    def visualizer(self):
        """Create GanttVisualizer instance."""
        return GanttVisualizer()
    
    def test_visualizer_creation(self):
        """Test visualizer creation with default color."""
        viz = GanttVisualizer()
        assert viz.color_by == "task_type"
    
    def test_visualizer_color_by_name(self):
        """Test visualizer with color_by='task_name'."""
        viz = GanttVisualizer(color_by="task_name")
        assert viz.color_by == "task_name"
    
    def test_draw_returns_figure(self, visualizer, sample_result):
        """Test draw returns a Plotly figure."""
        fig = visualizer.draw(sample_result)
        assert fig is not None
        assert hasattr(fig, 'data')
        assert hasattr(fig, 'layout')
    
    def test_draw_with_custom_title(self, visualizer, sample_result):
        """Test draw with custom title."""
        fig = visualizer.draw(sample_result, title="My Custom Schedule")
        assert "My Custom Schedule" in fig.layout.title.text
    
    def test_draw_empty_schedule(self, visualizer, empty_result):
        """Test draw with empty/failed result."""
        fig = visualizer.draw(empty_result)
        assert fig is not None
    
    def test_draw_contains_tasks(self, visualizer, sample_result):
        """Test that drawn figure contains task data."""
        fig = visualizer.draw(sample_result)
        assert len(fig.data) > 0
    
    def test_metrics_annotation(self, visualizer, sample_result):
        """Test that metrics are shown in annotation."""
        fig = visualizer.draw(sample_result)
        assert len(fig.layout.annotations) > 0


class TestDependencyGraphVisualizer:
    """Tests for DependencyGraphVisualizer."""
    
    @pytest.fixture
    def visualizer(self):
        """Create DependencyGraphVisualizer instance."""
        return DependencyGraphVisualizer()
    
    def test_visualizer_creation(self, visualizer):
        """Test visualizer has default properties."""
        assert visualizer.node_radius > 0
        assert visualizer.h_spacing > 0
        assert visualizer.v_spacing > 0
    
    def test_draw_returns_figure(self, visualizer, job_problem):
        """Test draw returns a Plotly figure."""
        fig = visualizer.draw(job_problem)
        assert fig is not None
        assert hasattr(fig, 'data')
        assert hasattr(fig, 'layout')
    
    def test_draw_with_custom_title(self, visualizer, job_problem):
        """Test draw with custom title."""
        fig = visualizer.draw(job_problem, title="My Dependencies")
        assert "My Dependencies" in fig.layout.title.text
    
    def test_draw_empty_problem(self, visualizer, empty_problem):
        """Test draw with empty problem."""
        fig = visualizer.draw(empty_problem)
        assert fig is not None
    
    def test_draw_contains_nodes(self, visualizer, job_problem):
        """Test that figure contains node shapes."""
        fig = visualizer.draw(job_problem)
        assert len(fig.layout.shapes) > 0
    
    def test_draw_contains_job_box(self, visualizer, job_problem):
        """Test that job bounding box is drawn."""
        fig = visualizer.draw(job_problem)
        rect_shapes = [s for s in fig.layout.shapes if s.type == "rect"]
        assert len(rect_shapes) >= 1
    
    def test_make_short_name(self, visualizer):
        """Test short name generation."""
        assert visualizer._make_short_name("Weld_Part_A") == "WPA"
        assert visualizer._make_short_name("Paint-B") == "PB"
        assert visualizer._make_short_name("VeryLongTaskName") == "VeryLong"
    
    def test_group_identical_jobs(self, visualizer):
        """Test job grouping logic."""
        job1 = Job(id="J1", name="Product", due_date=100, priority=1)
        job2 = Job(id="J2", name="Product", due_date=100, priority=1)
        job3 = Job(id="J3", name="Product", due_date=200, priority=1)
        
        groups = visualizer._group_identical_jobs([job1, job2, job3])
        
        assert len(groups) == 2
        batch_group = next(g for g in groups if g["count"] > 1)
        assert batch_group["count"] == 2
    
    def test_calculate_positions(self, visualizer, job_problem):
        """Test position calculation."""
        job_groups = visualizer._group_identical_jobs(job_problem.jobs)
        positions = visualizer._calculate_positions(job_groups, [])
        
        assert len(positions) == 2  # 2 tasks
        assert 1 in positions
        assert 2 in positions
        assert positions[1][0] < positions[2][0]  # Task 1 before Task 2
