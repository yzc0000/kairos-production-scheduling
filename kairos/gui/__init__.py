"""
Kairos GUI Package.

Provides a Streamlit-based web interface for scheduling problems
using three-field notation (α|β|γ).

Usage:
    kairos-gui  # or python -m kairos.gui
"""

from kairos.gui.notation_parser import NotationParser
from kairos.gui.solver_selector import SolverSelector

__all__ = ["NotationParser", "SolverSelector"]
