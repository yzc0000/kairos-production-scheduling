"""
Solver selector based on three-field notation.

Maps scheduling features to the appropriate solver.
"""

from kairos.gui.notation_parser import SchedulingFeatures
from kairos.solvers.factory import SolverType


class SolverSelector:
    """Select the best solver based on problem features."""
    
    @classmethod
    def get_solver_type(cls, features: SchedulingFeatures) -> SolverType:
        """
        Select the appropriate solver for given features.
        
        Mapping based on three-field notation:
        
        Single Machine (α = 1):
        - 1 || Cmax → SPT (Cmax always same)
        - 1 || ΣCj → SPT
        - 1 || ΣwjCj → WSPT
        - 1 | pmtn, rj | ΣCj → SRPT
        - 1 || Lmax → EDD
        - 1 || ΣTj → CP_SAT
        
        Parallel Machines (α = Pm):
        - Pm | pmtn | Cmax → MCNAUGHTON
        - Pm | pmtn, rj | ΣCj → SRPT
        - Pm || Cmax → LPT
        - Pm || ΣCj → SPT
        
        Flow Shop / Job Shop (α = Fm, Jm):
        - All → CP_SAT
        """
        mt = features.machine_type
        obj = features.objective
        pmtn = features.preemption
        
        # Flow Shop / Job Shop → CP_SAT
        if mt in ("Fm", "Jm", "Om"):
            return SolverType.CP_SAT
        
        # Single Machine
        if mt == "1":
            if pmtn:
                return SolverType.SRPT
            if obj in ("Cmax", "ΣCj"):
                return SolverType.SPT
            if obj == "ΣwjCj":
                return SolverType.WSPT
            if obj == "Lmax":
                return SolverType.EDD
            if obj in ("ΣTj", "ΣwjTj"):
                return SolverType.CP_SAT
        
        # Parallel Machines
        if mt in ("Pm", "Qm"):
            if pmtn:
                if obj == "Cmax":
                    return SolverType.MCNAUGHTON
                else:
                    return SolverType.SRPT
            else:
                if obj == "Cmax":
                    return SolverType.LPT
                if obj in ("ΣCj", "ΣwjCj"):
                    return SolverType.SPT
        
        # Default fallback
        return SolverType.CP_SAT
    
    @classmethod
    def get_solver_name(cls, solver_type: SolverType) -> str:
        """Get human-readable solver name."""
        names = {
            SolverType.CP_SAT: "Google CP-SAT (Constraint Programming)",
            SolverType.SPT: "SPT (Shortest Processing Time)",
            SolverType.LPT: "LPT (Longest Processing Time)",
            SolverType.EDD: "EDD (Earliest Due Date)",
            SolverType.WSPT: "WSPT (Weighted Shortest Processing Time)",
            SolverType.SRPT: "SRPT (Shortest Remaining Processing Time)",
            SolverType.MCNAUGHTON: "McNaughton's Algorithm",
        }
        return names.get(solver_type, str(solver_type))
    
    @classmethod
    def is_optimal(cls, solver_type: SolverType, features: SchedulingFeatures) -> bool:
        """Check if the solver gives optimal results for these features."""
        optimal_cases = {
            # Single machine optimal cases
            (SolverType.SPT, "1", "ΣCj"),
            (SolverType.WSPT, "1", "ΣwjCj"),
            (SolverType.EDD, "1", "Lmax"),
            (SolverType.SRPT, "1", "ΣCj"),
            # Parallel machine optimal cases
            (SolverType.MCNAUGHTON, "Pm", "Cmax"),
        }
        
        if features.preemption and solver_type in (SolverType.SRPT, SolverType.MCNAUGHTON):
            return True
        
        return (solver_type, features.machine_type, features.objective) in optimal_cases
