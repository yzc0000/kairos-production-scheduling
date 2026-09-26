"""
Solver factory and solver type enumeration.

Provides a clean API for getting solver instances by type.
"""

from enum import Enum

from kairos.solvers.base_solver import BaseSolver


class SolverType(str, Enum):
    """Available solver types."""
    CP_SAT = "google_cp"
    # Heuristic solvers (non-preemptive)
    SPT = "spt"          # Shortest Processing Time
    LPT = "lpt"          # Longest Processing Time
    EDD = "edd"          # Earliest Due Date
    WSPT = "wspt"        # Weighted Shortest Processing Time
    # Heuristic solvers (preemptive)
    SRPT = "srpt"        # Shortest Remaining Processing Time
    MCNAUGHTON = "mcnaughton"  # McNaughton's Wrap-Around (Cmax optimal)


class ObjectiveType(int, Enum):
    """
    Objective function type for solver optimization.
    
    MAKESPAN: Minimize the maximum job completion time
    WEIGHTED_TARDINESS: Minimize sum of (tardiness * priority) for all jobs
    """
    MAKESPAN = 0
    WEIGHTED_TARDINESS = 1


class SolverFactory:
    """
    Factory for creating solver instances.
    
    Usage:
        solver = SolverFactory.get_solver(SolverType.CP_SAT)
        result = solver.solve(problem)
    """
    
    _solvers = {}
    
    @classmethod
    def register(cls, solver_type: SolverType, solver_class: type) -> None:
        """Register a solver class for a given type."""
        cls._solvers[solver_type] = solver_class
    
    @classmethod
    def get_solver(cls, solver_type: SolverType, **kwargs) -> BaseSolver:
        """
        Get a solver instance for the given type.
        
        Args:
            solver_type: The type of solver to create.
            **kwargs: Attributes to set on the solver instance.

                For all solvers:
                - objective_type (ObjectiveType): The objective function to use
                - logging_enabled (bool): Enable kairos solver logging
                
                For CP_SAT solver:
                - ortools_logging (bool): Enable OR-Tools search progress logging
                - CIRCUIT_THRESHOLD (int): Use CIRCUIT if n > this
            
        Returns:
            An instance of the requested solver.
            
        Raises:
            ValueError: If the solver type is not registered.
        """
        # Lazy import to avoid circular dependencies
        if not cls._solvers:
            cls._register_default_solvers()
        
        if solver_type not in cls._solvers:
            available = ", ".join(t.value for t in cls._solvers.keys())
            raise ValueError(
                f"Unknown solver type: {solver_type}. "
                f"Available solvers: {available}"
            )
        
        return cls._solvers[solver_type](**kwargs)
    
    @classmethod
    def _register_default_solvers(cls) -> None:
        """Register all built-in solvers."""
        from kairos.solvers.google_cp import GoogleCPSATSolver
        from kairos.solvers.heuristics import (
            SPTSolver, LPTSolver, EDDSolver, WSPTSolver, SRPTSolver, McNaughtonSolver
        )
        
        cls.register(SolverType.CP_SAT, GoogleCPSATSolver)
        cls.register(SolverType.SPT, SPTSolver)
        cls.register(SolverType.LPT, LPTSolver)
        cls.register(SolverType.EDD, EDDSolver)
        cls.register(SolverType.WSPT, WSPTSolver)
        cls.register(SolverType.SRPT, SRPTSolver)
        cls.register(SolverType.MCNAUGHTON, McNaughtonSolver)
    
    @classmethod
    def list_solvers(cls) -> list:
        """List all available solver types."""
        return list(SolverType)
