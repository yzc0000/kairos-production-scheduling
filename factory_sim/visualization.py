from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .models import EPSILON, ScheduleBundle, SimulationResult

try:
    import plotly.express as px
    import plotly.graph_objects as go
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "plotly is required for schedule visualization. Install plotly to use factory_sim.visualization."
    ) from exc


@dataclass(frozen=True, slots=True)
class _GanttRow:
    row_kind: str
    label: str
    machine_name: str
    start: float
    finish: float
    duration: float
    color_value: str
    task_type: str
    family_label: str
    batch_label: str
    operation_id: str
    is_setup: bool
    details: dict[str, Any]


def _resolve_color_value(
    color_by: str,
    *,
    task_name: str,
    task_type: str,
    batch_id: str,
    product_id: str,
    family_label: str,
) -> str:
    if color_by == "task_name":
        return task_name
    if color_by == "task_type":
        return task_type
    if color_by == "batch_id":
        return batch_id
    if color_by in {"product_id", "product_family", "family_id", "job_family"}:
        return family_label
    return family_label


def _legend_title(color_by: str) -> str:
    if color_by == "task_name":
        return "Task"
    if color_by == "task_type":
        return "Task Type"
    if color_by == "batch_id":
        return "Batch"
    if color_by in {"product_id", "product_family", "family_id", "job_family"}:
        return "Product Family"
    return "Product Family"


def _empty_figure(title: str, message: str) -> "go.Figure":
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=20),
    )
    fig.update_layout(title=title)
    return fig


def _create_numeric_gantt(
    rows: list[_GanttRow],
    *,
    title: str,
    legend_title: str,
    show_task_names: bool,
    annotation_lines: list[str],
    machine_names: list[str] | None = None,
) -> "go.Figure":
    fig = go.Figure()
    if machine_names is None:
        machines = sorted({row.machine_name for row in rows})
    else:
        machines = list(dict.fromkeys(machine_names))
    palette_keys = [row.color_value for row in rows if row.row_kind == "task"]
    color_map = {
        key: px.colors.qualitative.Plotly[index % len(px.colors.qualitative.Plotly)]
        for index, key in enumerate(dict.fromkeys(palette_keys))
    }

    seen_legends: set[str] = set()
    for row in rows:
        if row.row_kind == "setup":
            marker = dict(
                color="rgba(128, 128, 128, 0.6)",
                pattern_shape="/",
                pattern_fillmode="overlay",
                line=dict(color="gray", width=1),
            )
        else:
            marker = dict(color=color_map[row.color_value])

        fig.add_trace(
            go.Bar(
                x=[row.duration],
                y=[row.machine_name],
                base=[row.start],
                orientation="h",
                name=row.color_value,
                marker=marker,
                text=row.label if show_task_names else None,
                textposition="inside",
                hovertemplate=(
                    f"<b>{row.label}</b><br>"
                    f"Family: {row.family_label}<br>"
                    f"Batch/Job: {row.batch_label}<br>"
                    f"Type: {row.task_type}<br>"
                    f"Machine: {row.machine_name}<br>"
                    f"Start: {row.start:.2f}<br>"
                    f"End: {row.finish:.2f}<br>"
                    f"Duration: {row.duration:.2f}<br>"
                    f"Operation ID: {row.operation_id}<br>"
                    f"{row.details['extra_hover']}"
                    "<extra></extra>"
                ),
                showlegend=(row.row_kind == "task") and row.color_value not in seen_legends,
            )
        )
        if row.row_kind == "task":
            seen_legends.add(row.color_value)

    rendered_machines = {row.machine_name for row in rows}
    for machine_name in machines:
        if machine_name in rendered_machines:
            continue
        fig.add_trace(
            go.Bar(
                x=[0.0],
                y=[machine_name],
                base=[0.0],
                orientation="h",
                name="_machine_placeholder",
                marker=dict(color="rgba(0, 0, 0, 0)"),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    fig.update_layout(
        title=title,
        barmode="overlay",
        xaxis=dict(title="Time (minutes)"),
        yaxis=dict(
            title="Machine",
            categoryorder="array",
            categoryarray=machines[::-1],
        ),
        showlegend=True,
        legend_title=legend_title,
        height=max(400, len(machines) * 80),
    )

    if annotation_lines:
        fig.add_annotation(
            text="<br>".join(annotation_lines),
            xref="paper",
            yref="paper",
            x=1,
            y=1.08,
            showarrow=False,
            font=dict(size=12, color="darkblue"),
            xanchor="right",
            align="right",
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="darkblue",
            borderwidth=1,
            borderpad=4,
        )

    return fig


class SimulationGanttVisualizer:
    def __init__(self, color_by: str = "family_id"):
        self.color_by = color_by

    def draw(
        self,
        result: SimulationResult,
        schedule_bundle: ScheduleBundle,
        title: str = "Simulation Schedule",
        show_task_names: bool = True,
    ) -> "go.Figure":
        rows, incomplete_count = self._build_rows(result, schedule_bundle)
        if not rows:
            return _empty_figure(title, "No completed simulation operations to display")

        metrics = [f"Displayed operations: {len([row for row in rows if row.row_kind == 'task'])}"]
        if incomplete_count:
            metrics.append(f"Incomplete operations skipped: {incomplete_count}")
        actual_end_times = [operation.actual_end for operation in result.operations if operation.actual_end is not None]
        if actual_end_times:
            metrics.append(f"Actual makespan: {max(actual_end_times):.2f} min")

        return _create_numeric_gantt(
            rows,
            title=title,
            legend_title=_legend_title(self.color_by),
            show_task_names=show_task_names,
            annotation_lines=metrics,
            machine_names=[
                machine.name or machine.machine_id for machine in schedule_bundle.machines.values()
            ],
        )

    def save_html(
        self,
        result: SimulationResult,
        schedule_bundle: ScheduleBundle,
        file_path: str,
        **kwargs: Any,
    ) -> None:
        fig = self.draw(result=result, schedule_bundle=schedule_bundle, **kwargs)
        fig.write_html(file_path)

    def _build_rows(
        self,
        result: SimulationResult,
        schedule_bundle: ScheduleBundle,
    ) -> tuple[list[_GanttRow], int]:
        schedule_by_operation = {
            operation.operation_id: operation for operation in schedule_bundle.schedule_operations
        }
        step_by_batch_and_step = {
            (batch.batch_id, step.step_id): step
            for batch in schedule_bundle.batches.values()
            for step in batch.route
        }

        rows_by_machine: dict[str, list[_GanttRow]] = defaultdict(list)
        incomplete_count = 0
        for operation in result.operations:
            if operation.actual_start is None or operation.actual_end is None:
                incomplete_count += 1
                continue

            definition = schedule_by_operation[operation.operation_id]
            batch = schedule_bundle.batches[operation.batch_id]
            step = step_by_batch_and_step[(operation.batch_id, operation.step_id)]
            machine = schedule_bundle.machines[operation.machine_id]

            task_name = str(definition.metadata.get("task_name") or step.name or operation.step_id)
            task_type = str(definition.metadata.get("setup_key") or batch.family_id or batch.product_id)
            family_label = str(batch.family_id or batch.product_id)
            batch_label = str(definition.metadata.get("job_id") or batch.batch_id)
            machine_name = machine.name or machine.machine_id
            color_value = _resolve_color_value(
                self.color_by,
                task_name=task_name,
                task_type=task_type,
                batch_id=batch.batch_id,
                product_id=batch.product_id,
                family_label=family_label,
            )

            if operation.setup_started_at is not None and operation.actual_start - operation.setup_started_at > EPSILON:
                setup_finish = min(
                    operation.actual_start,
                    operation.setup_started_at + operation.sampled_setup_time,
                )
                if setup_finish - operation.setup_started_at > EPSILON:
                    rows_by_machine[machine_name].append(
                        _GanttRow(
                            row_kind="setup",
                            label=f"Setup->{task_name}",
                            machine_name=machine_name,
                            start=operation.setup_started_at,
                            finish=setup_finish,
                            duration=setup_finish - operation.setup_started_at,
                            color_value="Setup",
                            task_type="Setup",
                            family_label=family_label,
                            batch_label=batch_label,
                            operation_id=f"setup::{operation.operation_id}",
                            is_setup=True,
                            details={
                                "extra_hover": (
                                    f"Planned start: {definition.planned_start:.2f}<br>"
                                    f"Planned end: {definition.planned_end:.2f}<br>"
                                    f"Active setup duration: {operation.sampled_setup_time:.2f}<br>"
                                )
                            },
                        )
                    )

            rows_by_machine[machine_name].append(
                _GanttRow(
                    row_kind="task",
                    label=task_name,
                    machine_name=machine_name,
                    start=operation.actual_start,
                    finish=operation.actual_end,
                    duration=operation.actual_end - operation.actual_start,
                    color_value=color_value,
                    task_type=task_type,
                    family_label=family_label,
                    batch_label=batch_label,
                    operation_id=operation.operation_id,
                    is_setup=False,
                    details={
                        "extra_hover": (
                            f"Planned start: {definition.planned_start:.2f}<br>"
                            f"Planned end: {definition.planned_end:.2f}<br>"
                            f"Batch ID: {batch.batch_id}<br>"
                            f"Product ID: {batch.product_id}<br>"
                        )
                    },
                )
            )
        return _flatten_rows(rows_by_machine), incomplete_count


class KairosGanttVisualizer:
    def __init__(self, color_by: str = "job_family"):
        self.color_by = color_by

    def draw(
        self,
        result: Any,
        title: str = "Kairos Schedule",
        show_task_names: bool = True,
        machine_names: list[str] | None = None,
    ) -> "go.Figure":
        rows = self._build_rows(result)
        if not rows:
            return _empty_figure(title, "No valid Kairos schedule to display")

        metrics: list[str] = []
        status = getattr(result, "status", None)
        if status:
            metrics.append(f"Status: {status}")
        makespan = getattr(result, "makespan", None)
        if makespan is not None:
            metrics.append(f"Makespan: {float(makespan):.2f} min")
        objective_value = getattr(result, "objective_value", None)
        if objective_value is not None:
            metrics.append(f"Objective: {objective_value}")

        return _create_numeric_gantt(
            rows,
            title=title,
            legend_title=_legend_title(self.color_by),
            show_task_names=show_task_names,
            annotation_lines=metrics,
            machine_names=machine_names,
        )

    def save_html(self, result: Any, file_path: str, **kwargs: Any) -> None:
        fig = self.draw(result=result, **kwargs)
        fig.write_html(file_path)

    def _build_rows(self, result: Any) -> list[_GanttRow]:
        if not getattr(result, "is_success", False) or not getattr(result, "schedule", None):
            return []

        machine_tasks: dict[str, list[Any]] = defaultdict(list)
        for task in result.schedule:
            machine_tasks[task.machine_name].append(task)

        rows_by_machine: dict[str, list[_GanttRow]] = defaultdict(list)
        for machine_name, tasks in machine_tasks.items():
            ordered_tasks = sorted(tasks, key=lambda item: (item.start_time, item.end_time, str(item.task_id)))
            previous_task: Any | None = None
            for task in ordered_tasks:
                family_label = str(
                    task.job.task_type
                    if task.job is not None and task.job.task_type is not None
                    else task.job.name
                    if task.job is not None
                    else "Standalone"
                )
                batch_label = str(task.job.name if task.job is not None else "Standalone")
                task_name = str(task.task_name)
                task_type = str(task.task_type_name or task.task_type or task.task_name)
                color_value = _resolve_color_value(
                    self.color_by,
                    task_name=task_name,
                    task_type=task_type,
                    batch_id=str(task.job_id or task.task_id),
                    product_id=batch_label,
                    family_label=family_label,
                )

                if (
                    previous_task is not None
                    and previous_task.end_time < task.start_time
                    and previous_task.task.get_effective_task_type() != task.task.get_effective_task_type()
                    and float(task.setup_time) > 0
                ):
                    setup_start = float(task.start_time) - float(task.setup_time)
                    rows_by_machine[machine_name].append(
                        _GanttRow(
                            row_kind="setup",
                            label=f"Setup->{task_name}",
                            machine_name=machine_name,
                            start=setup_start,
                            finish=float(task.start_time),
                            duration=float(task.setup_time),
                            color_value="Setup",
                            task_type="Setup",
                            family_label=family_label,
                            batch_label=batch_label,
                            operation_id=f"setup::{task.task_id}",
                            is_setup=True,
                            details={
                                "extra_hover": (
                                    f"Task ID: {task.task_id}<br>"
                                    f"Setup duration: {float(task.setup_time):.2f}<br>"
                                )
                            },
                        )
                    )

                rows_by_machine[machine_name].append(
                    _GanttRow(
                        row_kind="task",
                        label=task_name,
                        machine_name=machine_name,
                        start=float(task.start_time),
                        finish=float(task.end_time),
                        duration=float(task.duration),
                        color_value=color_value,
                        task_type=task_type,
                        family_label=family_label,
                        batch_label=batch_label,
                        operation_id=str(task.task_id),
                        is_setup=False,
                        details={
                            "extra_hover": (
                                f"Job ID: {task.job_id}<br>"
                                f"Machine ID: {task.machine_id}<br>"
                            )
                        },
                    )
                )
                previous_task = task

        return _flatten_rows(rows_by_machine)


def _flatten_rows(rows_by_machine: dict[str, list[_GanttRow]]) -> list[_GanttRow]:
    all_rows: list[_GanttRow] = []
    for _, machine_rows in rows_by_machine.items():
        ordered_rows = sorted(machine_rows, key=lambda row: (row.start, row.finish, row.operation_id))
        for row in ordered_rows:
            all_rows.append(row)
    return all_rows
