"""
Three-field notation parser.

Parses scheduling problem notation (α|β|γ) into features.
"""

from dataclasses import dataclass, field
from typing import Set


@dataclass
class SchedulingFeatures:
    """Features extracted from three-field notation."""
    
    # α (Machine environment)
    machine_type: str = "1"  # "1", "Pm", "Qm", "Fm", "Jm", "Om"
    num_machines: int = 1
    
    # β (Constraints)
    preemption: bool = False      # pmtn
    release_times: bool = False   # rj
    precedence: bool = False      # prec
    setup_times: bool = False     # sij
    due_dates: bool = False       # dj
    
    # γ (Objective)
    objective: str = "Cmax"  # "Cmax", "ΣCj", "ΣwjCj", "Lmax", "ΣTj", "ΣwjTj"
    
    def get_notation(self) -> str:
        """Return the three-field notation string."""
        beta_parts = []
        if self.preemption:
            beta_parts.append("pmtn")
        if self.release_times:
            beta_parts.append("rj")
        if self.precedence:
            beta_parts.append("prec")
        if self.setup_times:
            beta_parts.append("sij")
        if self.due_dates:
            beta_parts.append("dj")
        
        beta = ", ".join(beta_parts) if beta_parts else ""
        return f"{self.machine_type} | {beta} | {self.objective}"


class NotationParser:
    """Parse three-field notation into features."""
    
    # Valid options
    MACHINE_TYPES = ["1", "Pm", "Qm", "Fm", "Jm", "Om"]
    CONSTRAINTS = ["pmtn", "rj", "prec", "sij", "dj"]
    OBJECTIVES = ["Cmax", "ΣCj", "ΣwjCj", "Lmax", "ΣTj", "ΣwjTj"]
    
    @classmethod
    def parse(cls, notation: str) -> SchedulingFeatures:
        """
        Parse a three-field notation string.
        
        Args:
            notation: String like "Pm | rj, pmtn | Cmax"
            
        Returns:
            SchedulingFeatures object
        """
        parts = [p.strip() for p in notation.split("|")]
        if len(parts) != 3:
            raise ValueError(f"Invalid notation: expected 3 parts, got {len(parts)}")
        
        alpha, beta, gamma = parts
        
        features = SchedulingFeatures()
        
        # Parse α (machine environment)
        features.machine_type = alpha.strip() or "1"
        if features.machine_type.startswith("P") or features.machine_type.startswith("Q"):
            features.num_machines = 0  # User will input
        
        # Parse β (constraints)
        if beta.strip():
            constraints = [c.strip() for c in beta.split(",")]
            for c in constraints:
                if c == "pmtn":
                    features.preemption = True
                elif c == "rj":
                    features.release_times = True
                elif c == "prec":
                    features.precedence = True
                elif c == "sij":
                    features.setup_times = True
                elif c == "dj":
                    features.due_dates = True
        
        # Parse γ (objective)
        features.objective = gamma.strip() or "Cmax"
        
        return features
    
    @classmethod
    def from_components(
        cls,
        machine_type: str,
        constraints: Set[str],
        objective: str,
        num_machines: int = 1
    ) -> SchedulingFeatures:
        """
        Create features from UI components.
        
        Args:
            machine_type: "1", "Pm", etc.
            constraints: Set of constraint codes
            objective: Objective function
            num_machines: Number of machines (for Pm, etc.)
        """
        features = SchedulingFeatures(
            machine_type=machine_type,
            num_machines=num_machines,
            objective=objective,
            preemption="pmtn" in constraints,
            release_times="rj" in constraints,
            precedence="prec" in constraints,
            setup_times="sij" in constraints,
            due_dates="dj" in constraints,
        )
        return features
