"""
Kairos - Industrial Job Shop Scheduling Library

Usage:
    import kairos as kr
    problem = kr.SchedulingProblem()
    solver = kr.SolverFactory.get_solver(kr.SolverType.CP_SAT)
    result = solver.solve(problem)
"""

# Domain Models
from kairos.domain.models import (
    Task,
    Job,
    Machine,
    SchedulingProblem,
    TaskType,
    SolutionResult,
    ProblemFeature,
)

# Solver Layer
from kairos.solvers import SolverFactory, SolverType, ObjectiveType

# Data Layer
from kairos.data.excel_loader import ExcelDataLoader

# Visualization
from kairos.visualization.gantt import GanttVisualizer
from kairos.visualization.dependency_graph import DependencyGraphVisualizer

__version__ = "0.1.0"
__all__ = [
    # Domain
    "Task",
    "Job",
    "Machine",
    "SchedulingProblem",
    "TaskType",
    "ObjectiveType",
    "SolutionResult",
    "ProblemFeature",
    # Solvers
    "SolverFactory",
    "SolverType",
    # Data
    "ExcelDataLoader",
    # Visualization
    "GanttVisualizer",
    "DependencyGraphVisualizer",
]
