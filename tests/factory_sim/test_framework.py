from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factory_sim import (
    SimulationHooks,
    ValidationError,
    build_batch,
    build_basket_rule,
    build_calendar,
    build_distribution,
    build_failure_profile,
    build_machine,
    build_product_tracker_lines,
    build_route_step,
    build_schedule_bundle,
    build_schedule_operation,
    build_time_window,
    build_travel_matrix,
    run_week,
)


SIMPY_AVAILABLE = importlib.util.find_spec("simpy") is not None


def deterministic(value: float):
    return build_distribution("deterministic", value=value)


def single_shift_calendar(end: float = 100.0):
    return build_calendar("default", [build_time_window(0.0, end)])


def one_step_batch(batch_id: str, product_id: str, quantity: float = 1.0, family_id: str | None = None, release: float = 0.0):
    step = build_route_step("step-1", sequence=1, process_time_per_unit=deterministic(1.0))
    return build_batch(batch_id, product_id=product_id, quantity=quantity, route=[step], family_id=family_id, release_time=release)


@unittest.skipUnless(SIMPY_AVAILABLE, "simpy is required for engine tests")
class SimulationFrameworkTests(unittest.TestCase):
    def test_machine_waits_for_next_scheduled_batch(self):
        machine = build_machine("M1", calendar=single_shift_calendar())
        batch_a = one_step_batch("A", "P1", release=10.0)
        batch_b = one_step_batch("B", "P1", release=0.0)
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch_a, batch_b],
            schedule_operations=[
                build_schedule_operation("A-1", "A", "step-1", "M1", 1, 20.0, 21.0),
                build_schedule_operation("B-1", "B", "step-1", "M1", 2, 30.0, 31.0),
            ],
            basket_rules=[build_basket_rule("M1", "P1", 1.0)],
        )

        result = run_week(bundle, seed=1)
        operations = {operation.operation_id: operation for operation in result.operations}
        self.assertEqual(10.0, operations["A-1"].actual_start)
        self.assertEqual(11.0, operations["B-1"].actual_start)

    def test_trace_records_idle_reason_for_unavailable_next_job(self):
        machine = build_machine("M1", calendar=single_shift_calendar())
        batch_a = one_step_batch("A", "P1", release=10.0)
        batch_b = one_step_batch("B", "P1", release=0.0)
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch_a, batch_b],
            schedule_operations=[
                build_schedule_operation("A-1", "A", "step-1", "M1", 1, 20.0, 21.0),
                build_schedule_operation("B-1", "B", "step-1", "M1", 2, 30.0, 31.0),
            ],
            basket_rules=[build_basket_rule("M1", "P1", 1.0)],
        )

        result = run_week(bundle, seed=11, trace=True)
        idle_events = [event for event in result.events if event.event_type in {"idle_started", "idle_ended"}]

        self.assertTrue(any(event.details.get("idle_reason") == "waiting_for_release" for event in idle_events))
        self.assertTrue(any(event.event_type == "idle_started" for event in idle_events))
        self.assertTrue(any(event.event_type == "idle_ended" for event in idle_events))

    def test_product_tracker_formats_batch_lifecycle(self):
        machine = build_machine("M1", calendar=single_shift_calendar())
        batch = one_step_batch("A", "P1", release=0.0)
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch],
            schedule_operations=[build_schedule_operation("A-1", "A", "step-1", "M1", 1, 0.0, 1.0)],
            basket_rules=[build_basket_rule("M1", "P1", 1.0)],
        )

        result = run_week(bundle, seed=12, trace=True)
        lines = build_product_tracker_lines(bundle, result, include_idle=False)
        tracker_text = "\n".join(lines)

        self.assertIn("Batch A [P1] RELEASED into the system.", tracker_text)
        self.assertIn("Batch A [P1] STARTED step-1 on M1.", tracker_text)
        self.assertIn("Batch A [P1] COMPLETED step-1 on M1.", tracker_text)
        self.assertIn("Batch A [P1] COMPLETED.", tracker_text)

    def test_next_scheduled_batch_can_start_early(self):
        machine = build_machine("M1", calendar=single_shift_calendar())
        batch = one_step_batch("A", "P1", release=0.0)
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch],
            schedule_operations=[build_schedule_operation("A-1", "A", "step-1", "M1", 1, 20.0, 21.0)],
            basket_rules=[build_basket_rule("M1", "P1", 1.0)],
        )

        result = run_week(bundle, seed=2)
        self.assertEqual(0.0, result.operations[0].actual_start)

    def test_start_guard_hook_can_hold_processing_to_planned_time(self):
        machine = build_machine("M1", calendar=single_shift_calendar(), fixed_setup_time=2.0)
        batch_a = one_step_batch("A", "P1", family_id="F1")
        batch_b = one_step_batch("B", "P2", family_id="F2")
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch_a, batch_b],
            schedule_operations=[
                build_schedule_operation("A-1", "A", "step-1", "M1", 1, 0.0, 1.0),
                build_schedule_operation("B-1", "B", "step-1", "M1", 2, 5.0, 6.0),
            ],
            basket_rules=[
                build_basket_rule("M1", "P1", 1.0),
                build_basket_rule("M1", "P2", 1.0),
            ],
        )
        hooks = SimulationHooks(
            earliest_setup_start=lambda machine, operation, batch, setup_time: operation.planned_start - setup_time,
        )

        result = run_week(bundle, seed=2, hooks=hooks)
        operations = {operation.operation_id: operation for operation in result.operations}
        self.assertEqual(3.0, operations["B-1"].setup_started_at)
        self.assertEqual(5.0, operations["B-1"].actual_start)

    def test_setup_can_happen_before_predecessors_arrive_when_hook_enabled(self):
        calendar = single_shift_calendar()
        m1 = build_machine("M1", calendar=calendar)
        m2 = build_machine("M2", calendar=calendar)
        m3 = build_machine("M3", calendar=calendar, fixed_setup_time=5.0)

        step_seed = build_route_step("seed", 1, deterministic(10.0))
        seed_batch = build_batch("SEED", "P0", 1.0, route=[step_seed], family_id="F0")

        step_left = build_route_step("left", 1, deterministic(20.0), predecessor_step_ids=())
        step_right = build_route_step("right", 2, deterministic(20.0), predecessor_step_ids=())
        step_assembly = build_route_step("assembly", 3, deterministic(10.0), predecessor_step_ids=("left", "right"))
        assembly_batch = build_batch("ASM", "P1", 1.0, route=[step_left, step_right, step_assembly], family_id="F1")

        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[m1, m2, m3],
            batches=[seed_batch, assembly_batch],
            schedule_operations=[
                build_schedule_operation("SEED-1", "SEED", "seed", "M3", 1, 0.0, 10.0),
                build_schedule_operation("ASM-L", "ASM", "left", "M1", 1, 0.0, 20.0),
                build_schedule_operation("ASM-R", "ASM", "right", "M2", 1, 0.0, 20.0),
                build_schedule_operation("ASM-A", "ASM", "assembly", "M3", 2, 20.0, 30.0),
            ],
            basket_rules=[
                build_basket_rule("M1", "P1", 1.0),
                build_basket_rule("M2", "P1", 1.0),
                build_basket_rule("M3", "P0", 1.0),
                build_basket_rule("M3", "P1", 1.0),
            ],
            travel_matrix=build_travel_matrix({
                ("M1", "M3"): 0.0,
                ("M2", "M3"): 0.0,
            }),
        )
        hooks = SimulationHooks(
            earliest_setup_start=lambda machine, operation, batch, setup_time: operation.planned_start - setup_time,
            setup_before_availability=lambda machine, operation, batch: True,
        )

        result = run_week(bundle, seed=3, hooks=hooks)
        operations = {operation.operation_id: operation for operation in result.operations}
        self.assertEqual(15.0, operations["ASM-A"].setup_started_at)
        self.assertEqual(20.0, operations["ASM-A"].actual_start)

    def test_basket_accumulates_until_full_then_releases(self):
        machine = build_machine("M1", calendar=single_shift_calendar())
        batch_a = one_step_batch("A", "P1", quantity=1.0)
        batch_b = one_step_batch("B", "P1", quantity=1.0)
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch_a, batch_b],
            schedule_operations=[
                build_schedule_operation("A-1", "A", "step-1", "M1", 1, 0.0, 1.0),
                build_schedule_operation("B-1", "B", "step-1", "M1", 2, 2.0, 3.0),
            ],
            basket_rules=[build_basket_rule("M1", "P1", 2.0)],
        )

        result = run_week(bundle, seed=3)
        operations = {operation.operation_id: operation for operation in result.operations}
        self.assertEqual(2.0, operations["A-1"].release_time)
        self.assertEqual(2.0, operations["B-1"].release_time)
        self.assertEqual(2.0, result.batch_summaries[0].finished_at)

    def test_basket_release_keeps_separate_travel_times(self):
        calendar = single_shift_calendar()
        m1 = build_machine("M1", calendar=calendar)
        m2 = build_machine("M2", calendar=calendar)
        m3 = build_machine("M3", calendar=calendar)

        step_1 = build_route_step("cut", 1, deterministic(1.0))
        step_2 = build_route_step("finish", 2, deterministic(1.0))

        batch_a = build_batch("A", "P1", 1.0, route=[step_1, step_2])
        batch_b = build_batch("B", "P1", 1.0, route=[step_1, step_2])

        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[m1, m2, m3],
            batches=[batch_a, batch_b],
            schedule_operations=[
                build_schedule_operation("A-1", "A", "cut", "M1", 1, 0.0, 1.0),
                build_schedule_operation("B-1", "B", "cut", "M1", 2, 1.0, 2.0),
                build_schedule_operation("A-2", "A", "finish", "M2", 1, 5.0, 6.0),
                build_schedule_operation("B-2", "B", "finish", "M3", 1, 5.0, 6.0),
            ],
            basket_rules=[
                build_basket_rule("M1", "P1", 2.0),
                build_basket_rule("M2", "P1", 1.0),
                build_basket_rule("M3", "P1", 1.0),
            ],
            travel_matrix=build_travel_matrix({("M1", "M2"): 3.0, ("M1", "M3"): 5.0}),
        )

        result = run_week(bundle, seed=4)
        operations = {operation.operation_id: operation for operation in result.operations}
        self.assertEqual(5.0, operations["A-2"].actual_start)
        self.assertEqual(7.0, operations["B-2"].actual_start)

    def test_setup_only_on_product_change(self):
        machine = build_machine("M1", calendar=single_shift_calendar(), fixed_setup_time=2.0)
        batch_a = one_step_batch("A", "P1", family_id="F1")
        batch_b = one_step_batch("B", "P2", family_id="F2")
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch_a, batch_b],
            schedule_operations=[
                build_schedule_operation("A-1", "A", "step-1", "M1", 1, 0.0, 1.0),
                build_schedule_operation("B-1", "B", "step-1", "M1", 2, 1.0, 4.0),
            ],
            basket_rules=[
                build_basket_rule("M1", "P1", 1.0),
                build_basket_rule("M1", "P2", 1.0),
            ],
        )

        result = run_week(bundle, seed=5)
        operations = {operation.operation_id: operation for operation in result.operations}
        self.assertEqual(0.0, operations["A-1"].actual_start)
        self.assertEqual(3.0, operations["B-1"].actual_start)
        self.assertEqual(2.0, operations["B-1"].sampled_setup_time)

    def test_breakdown_pauses_and_resumes_same_batch(self):
        failure_profile = build_failure_profile(
            "fail-fast",
            uptime_distribution=deterministic(1.0),
            repair_distribution=deterministic(2.0),
        )
        machine = build_machine("M1", calendar=single_shift_calendar(), failure_profile=failure_profile)
        step = build_route_step("step-1", 1, deterministic(3.0))
        batch = build_batch("A", "P1", 1.0, route=[step])
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch],
            schedule_operations=[build_schedule_operation("A-1", "A", "step-1", "M1", 1, 0.0, 3.0)],
            basket_rules=[build_basket_rule("M1", "P1", 1.0)],
        )

        result = run_week(bundle, seed=6)
        self.assertEqual(7.0, result.operations[0].actual_end)

    def test_shift_pause_resumes_next_window(self):
        calendar = build_calendar("split", [build_time_window(0.0, 1.0), build_time_window(3.0, 10.0)])
        machine = build_machine("M1", calendar=calendar)
        step = build_route_step("step-1", 1, deterministic(2.0))
        batch = build_batch("A", "P1", 1.0, route=[step])
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch],
            schedule_operations=[build_schedule_operation("A-1", "A", "step-1", "M1", 1, 0.0, 2.0)],
            basket_rules=[build_basket_rule("M1", "P1", 1.0)],
        )

        result = run_week(bundle, seed=7)
        self.assertEqual(4.0, result.operations[0].actual_end)

    def test_week_end_marks_leftover(self):
        machine = build_machine("M1", calendar=single_shift_calendar(end=2.0))
        step = build_route_step("step-1", 1, deterministic(5.0))
        batch = build_batch("A", "P1", 1.0, route=[step])
        bundle = build_schedule_bundle(
            week_horizon=2.0,
            machines=[machine],
            batches=[batch],
            schedule_operations=[build_schedule_operation("A-1", "A", "step-1", "M1", 1, 0.0, 2.0)],
            basket_rules=[build_basket_rule("M1", "P1", 1.0)],
        )

        result = run_week(bundle, seed=8)
        self.assertEqual("in_process", result.leftover_batches[0].current_stage)
        self.assertIsNone(result.operations[0].actual_end)

    def test_multi_predecessor_operation_waits_for_all_inputs(self):
        calendar = single_shift_calendar()
        m1 = build_machine("M1", calendar=calendar)
        m2 = build_machine("M2", calendar=calendar)
        m3 = build_machine("M3", calendar=calendar)

        cut_left = build_route_step("cut-left", 1, deterministic(10.0), predecessor_step_ids=())
        cut_right = build_route_step("cut-right", 2, deterministic(10.0), predecessor_step_ids=())
        assembly = build_route_step(
            "assembly",
            3,
            deterministic(5.0),
            predecessor_step_ids=("cut-left", "cut-right"),
        )
        batch = build_batch("A", "P1", 1.0, route=[cut_left, cut_right, assembly])

        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[m1, m2, m3],
            batches=[batch],
            schedule_operations=[
                build_schedule_operation("A-cut-left", "A", "cut-left", "M1", 1, 0.0, 10.0),
                build_schedule_operation("A-cut-right", "A", "cut-right", "M2", 1, 0.0, 10.0),
                build_schedule_operation("A-assembly", "A", "assembly", "M3", 1, 15.0, 20.0),
            ],
            basket_rules=[
                build_basket_rule("M1", "P1", 1.0),
                build_basket_rule("M2", "P1", 1.0),
                build_basket_rule("M3", "P1", 1.0),
            ],
            travel_matrix=build_travel_matrix({
                ("M1", "M3"): 5.0,
                ("M2", "M3"): 2.0,
            }),
        )

        result = run_week(bundle, seed=9)
        operations = {operation.operation_id: operation for operation in result.operations}
        self.assertEqual(10.0, operations["A-cut-left"].release_time)
        self.assertEqual(10.0, operations["A-cut-right"].release_time)
        self.assertEqual(15.0, operations["A-assembly"].actual_start)

    def test_batch_completion_waits_for_all_terminal_operations(self):
        calendar = single_shift_calendar()
        m1 = build_machine("M1", calendar=calendar)
        m2 = build_machine("M2", calendar=calendar)

        step_a = build_route_step("step-a", 1, deterministic(1.0), predecessor_step_ids=())
        step_b = build_route_step("step-b", 2, deterministic(3.0), predecessor_step_ids=())
        batch = build_batch("A", "P1", 1.0, route=[step_a, step_b])

        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[m1, m2],
            batches=[batch],
            schedule_operations=[
                build_schedule_operation("A-1", "A", "step-a", "M1", 1, 0.0, 1.0),
                build_schedule_operation("A-2", "A", "step-b", "M2", 1, 0.0, 3.0),
            ],
            basket_rules=[
                build_basket_rule("M1", "P1", 1.0),
                build_basket_rule("M2", "P1", 1.0),
            ],
        )

        result = run_week(bundle, seed=10)
        self.assertTrue(result.batch_summaries[0].completed)
        self.assertEqual(3.0, result.batch_summaries[0].finished_at)


class ValidationTests(unittest.TestCase):
    def test_builder_can_create_valid_bundle(self):
        machine = build_machine("M1", calendar=single_shift_calendar())
        batch = one_step_batch("A", "P1")
        bundle = build_schedule_bundle(
            week_horizon=100.0,
            machines=[machine],
            batches=[batch],
            schedule_operations=[build_schedule_operation("A-1", "A", "step-1", "M1", 1, 0.0, 1.0)],
            basket_rules=[build_basket_rule("M1", "P1", 1.0)],
        )
        self.assertEqual("M1", next(iter(bundle.machines.values())).machine_id)

    def test_validation_rejects_product_switch_before_basket_empties(self):
        machine = build_machine("M1", calendar=single_shift_calendar())
        batch_a = one_step_batch("A", "P1", quantity=1.0)
        batch_b = one_step_batch("B", "P2", quantity=1.0)

        with self.assertRaises(ValidationError):
            build_schedule_bundle(
                week_horizon=10.0,
                machines=[machine],
                batches=[batch_a, batch_b],
                schedule_operations=[
                    build_schedule_operation("A-1", "A", "step-1", "M1", 1, 0.0, 1.0),
                    build_schedule_operation("B-1", "B", "step-1", "M1", 2, 1.0, 2.0),
                ],
                basket_rules=[
                    build_basket_rule("M1", "P1", 2.0),
                    build_basket_rule("M1", "P2", 1.0),
                ],
            )

    def test_validation_rejects_unknown_predecessor_step(self):
        machine = build_machine("M1", calendar=single_shift_calendar())
        step_a = build_route_step("step-a", 1, deterministic(1.0))
        step_b = build_route_step("step-b", 2, deterministic(1.0), predecessor_step_ids=("missing-step",))
        batch = build_batch("A", "P1", 1.0, route=[step_a, step_b])

        with self.assertRaises(ValidationError):
            build_schedule_bundle(
                week_horizon=100.0,
                machines=[machine],
                batches=[batch],
                schedule_operations=[
                    build_schedule_operation("A-1", "A", "step-a", "M1", 1, 0.0, 1.0),
                    build_schedule_operation("A-2", "A", "step-b", "M1", 2, 1.0, 2.0),
                ],
                basket_rules=[build_basket_rule("M1", "P1", 1.0)],
            )


if __name__ == "__main__":
    unittest.main()
