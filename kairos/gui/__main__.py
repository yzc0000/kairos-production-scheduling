"""
Kairos GUI module entry point.

Usage:
    python -m kairos.gui
    kairos-gui
"""

import subprocess
import sys
import os


def run_gui():
    """Launch the Streamlit GUI using subprocess."""
    # Find the app.py path
    app_path = os.path.join(os.path.dirname(__file__), "app.py")
    
    # Run streamlit
    subprocess.run([sys.executable, "-m", "streamlit", "run", app_path, "--server.headless", "true"])


if __name__ == "__main__":
    run_gui()
