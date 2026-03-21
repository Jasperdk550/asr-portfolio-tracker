"""
main.py — Entry Point
---------------------
Launches the CLI application.  All logic lives in the MVC layers:
  models/     → data, calculations, persistence
  views/      → terminal output, charts
  controllers/→ CLI command handling
"""

import sys
import os

# Ensure the project root is on the Python path
sys.path.insert(0, os.path.dirname(__file__))

from controllers.portfolio_controller import cli

if __name__ == "__main__":
    cli()
