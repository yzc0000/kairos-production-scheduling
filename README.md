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
src/validation/    JSPLIB benchmark parser, runner, and feasibility checks
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

## Validation results

### Deterministic scheduling and simulation

| Validation | Result |
|---|---|
| JSPLIB / OR-Library `ft06` benchmark | Found the known optimal makespan of **55** for the 6-job, 6-machine instance. Schedule feasibility checks passed. |
| Weighted-tardiness objective | The solver selected the priority-sensitive order with a weighted tardiness of **3**, compared with **20** for the reversed sequence. |
| Scheduler-to-simulation validation | The deterministic factory simulation reproduced the Kairos schedule exactly, with a makespan difference of **0.0**. |

### Stochastic what-if study

The production scenario contains 5 jobs, 25 operations, and 9 resources across cutting, CNC machining, press forming, assembly, and packaging. The CP-SAT plan was optimal with a makespan of **102** and weighted tardiness of **0**. Each scenario was evaluated over **50 stochastic simulation replications**.

| Scenario | Mean makespan | 95% confidence interval | Mean weighted tardiness | Completion rate | Delay-risk rate |
|---|---:|---:|---:|---:|---:|
| Baseline variation | 108.91 | 108.16–109.66 | 14.41 | 100% | 14% |
| CNC breakdown | 148.60 | 140.15–157.05 | 60.22 | 100% | 90% |
| Assembly slowdown | 116.52 | 115.53–117.50 | 21.99 | 100% | 92% |

The baseline schedule completed all jobs in every replication, while the disruption scenarios quantified the impact of machine reliability and slower assembly processing on delivery risk.

## Testing

```bash
python -m pytest
```

## Author

Ahmed Yazıcı
