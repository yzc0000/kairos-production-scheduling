from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = PROJECT_ROOT / "Kairos-Scheduler-main"

for path in (PROJECT_ROOT, KAIROS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import kairos as kr

from factory_sim import build_schedule_bundle_from_kairos, validate_kairos_solution
from examples.kairos_validation_demo import build_large_demo_problem


def build_validation_problem() -> "kr.SchedulingProblem":
    problem = kr.SchedulingProblem(name="Kairos Validation Test")
    problem.add_machine(kr.Machine(id="SAW", name="Saw"))
    problem.add_machine(kr.Machine(id="PRESS", name="Press"))
    problem.add_machine(kr.Machine(id="ASM", name="Assembly"))

    job = kr.Job(id="JOB-1", name="Wheel Product", task_type="Wheel")

    cut = kr.Task(id="cut", name="Cut Rim", task_type="Cut", setup_time=2)
    cut.add_alternative("SAW", 10)

    press = kr.Task(id="press", name="Press Core", task_type="Press", setup_time=1)
    press.add_alternative("PRESS", 6)

    assemble = kr.Task(id="assemble", name="Wheel Assembly", task_type="Assembly", setup_time=5)
    assemble.add_alternative("ASM", 8)
    assemble.add_predecessor(cut)
    assemble.add_predecessor(press)

    pack = kr.Task(id="pack", name="Final Pack", task_type="Packaging", setup_time=4)
    pack.add_alternative("ASM", 7)
    pack.add_predecessor(assemble)

    job.add_task(cut)
    job.add_task(press)
    job.add_task(assemble)
    job.add_task(pack)
    problem.add_job(job)
    return problem


class KairosValidationTests(unittest.TestCase):
    def test_kairos_solution_matches_deterministic_simulation(self):
        problem = build_validation_problem()
        solver = kr.SolverFactory.get_solver(kr.SolverType.CP_SAT)
        solution = solver.solve(problem, time_limit_seconds=30)

        report = validate_kairos_solution(problem, solution, trace=False)

        self.assertTrue(solution.is_success)
        self.assertTrue(report.exact_match)
        self.assertEqual(0.0, report.makespan_delta)

    def test_conversion_preserves_merge_predecessors(self):
        problem = build_validation_problem()
        solver = kr.SolverFactory.get_solver(kr.SolverType.CP_SAT)
        solution = solver.solve(problem, time_limit_seconds=30)

        conversion = build_schedule_bundle_from_kairos(problem, solution)
        batch = next(iter(conversion.schedule_bundle.batches.values()))
        route_by_step = {step.step_id: step for step in batch.route}

        self.assertEqual(("cut", "press"), route_by_step["assemble"].predecessor_step_ids)
        self.assertEqual(("assemble",), route_by_step["pack"].predecessor_step_ids)

    def test_large_demo_problem_has_expected_scale(self):
        problem = build_large_demo_problem()

        self.assertGreaterEqual(len(problem.machines), 30)
        self.assertGreaterEqual(len(problem.tasks), 200)
        self.assertTrue(any(len(task.alternatives) > 1 for task in problem.tasks))
        self.assertTrue(any(len(task.predecessors) > 1 for task in problem.tasks))

    def test_large_demo_uses_family_specific_task_types_for_shared_stages(self):
        problem = build_large_demo_problem()
        assembly_tasks = [task for task in problem.tasks if task.name == "Assembly"]
        packaging_tasks = [task for task in problem.tasks if task.name == "Packaging"]

        self.assertEqual({"Assembly"}, {task.name for task in assembly_tasks})
        self.assertEqual({"Packaging"}, {task.name for task in packaging_tasks})
        self.assertGreaterEqual(len({str(task.task_type) for task in assembly_tasks}), 4)
        self.assertGreaterEqual(len({str(task.task_type) for task in packaging_tasks}), 4)


if __name__ == "__main__":
    unittest.main()
