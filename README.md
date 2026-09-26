# Kairos: Production Scheduling and Simulation

A senior design project for industrial job-shop scheduling and schedule validation. The project combines a constraint-programming scheduler with a discrete-event factory simulator, making it possible to create production schedules, test them under operational uncertainty, and inspect the results visually.

## What it does

- Optimizes job-shop schedules with Google OR-Tools CP-SAT
- Supports alternative machines, precedence constraints, release times, due dates, and sequence-dependent setup times
- Includes SPT, LPT, and EDD heuristic schedulers for comparison
- Imports scheduling problems from Excel workbooks
- Converts Kairos schedules into factory simulation inputs
- Simulates machine failures, production calendars, transfers, batch flows, and stochastic processing times with SimPy
- Validates planned schedules against simulated execution
- Produces interactive Plotly Gantt charts and product-tracking outputs

## Tech stack

Python, Google OR-Tools, SimPy, Plotly, Pandas, OpenPyXL, and Streamlit.

## Repository structure

```
factory_sim/       Factory simulation and validation framework
kairos/            Job-shop scheduling engine and solver implementations
examples/          End-to-end planning, validation, and stochastic scenarios
tests/             Unit and integration tests for both components
benchmarks/        Standard scheduling benchmark input
schedule_demo.html Interactive scheduling visualisation
```

## Getting started

Requires Python 3.11 or newer.

```bash
git clone https://github.com/yzc0000/kairos-production-scheduling.git
cd kairos-production-scheduling
python -m venv .venv
```

Activate the virtual environment, then install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run a complete scheduling and validation example:

```bash
python examples/kairos_validation_demo.py
```

Run the stochastic scenario:

```bash
python examples/kairos_stochastic_demo.py
```

## Testing

```bash
python -m pytest
```

## Author

Ahmed Yazıcı
