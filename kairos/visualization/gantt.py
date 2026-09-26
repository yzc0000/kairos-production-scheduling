"""
Gantt chart visualization for scheduling solutions.

Uses Plotly to create interactive Gantt charts showing
the schedule grouped by machine.
"""

from typing import Dict, List, Optional

import plotly.express as px  # For color palette only
import plotly.graph_objects as go

from kairos.domain.models import SolutionResult


class GanttVisualizer:
    """
    Create Gantt chart visualizations for scheduling solutions.
    
    Usage:
        visualizer = GanttVisualizer()
        fig = visualizer.draw(result)
        fig.show()  # or fig.write_html("schedule.html")
    """
    
    def __init__(self, color_by: str = "task_type"):
        """
        Initialize the visualizer.
        
        Args:
            color_by: What to color bars by - "task_type" or "task_name"
        """
        self.color_by = color_by
    
    def draw(
        self,
        result: SolutionResult,
        title: str = "Production Schedule",
        show_task_names: bool = True,
    ) -> go.Figure:
        """
        Create a Gantt chart from a solution result.
        
        Args:
            result: The SolutionResult from a solver.
            title: Chart title.
            show_task_names: Whether to show task names on bars.
            
        Returns:
            A Plotly Figure object.
        """
        if not result.is_success or not result.schedule:
            # Create empty figure with message
            fig = go.Figure()
            fig.add_annotation(
                text="No valid schedule to display",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=20)
            )
            fig.update_layout(title=title)
            return fig
        
        # Prepare data for Plotly - calculate setup times from schedule
        data = []
        setup_data = []
        
        # Group tasks by machine and sort by start time
        machine_tasks = {}
        for task in result.schedule:
            machine = task.machine_name
            if machine not in machine_tasks:
                machine_tasks[machine] = []
            machine_tasks[machine].append(task)
        
        for machine in machine_tasks:
            machine_tasks[machine].sort(key=lambda t: t.start_time)
        
        # Calculate setup times based on task_type changes
        for machine, tasks in machine_tasks.items():
            prev_task = None
            for task in tasks:
                # Use task_type_name if available
                type_name = task.task_type_name if task.task_type_name else f"Type {task.task_type}"
                job_name = task.job_name if task.job_name else "Standalone"
                
                # Calculate setup time (gap between previous end and current start on same machine)
                setup_time = 0
                if prev_task and prev_task.end_time < task.start_time:
                    # Check if types are different
                    prev_type = prev_task.task_type_name if prev_task.task_type_name else prev_task.task_type
                    curr_type = task.task_type_name if task.task_type_name else task.task_type
                    if prev_type != curr_type:
                        setup_time = task.setup_time
                        # Add setup bar
                        setup_data.append({
                            "Task": f"Setup→{task.task_name}",
                            "Machine": machine,
                            "Start": task.start_time - setup_time,
                            "Finish": task.start_time,
                            "Duration": setup_time,
                            "TaskType": "Setup",
                            "TaskID": f"setup_{task.task_id}",
                            "Job": job_name,
                            "IsSetup": True,
                        })
                
                data.append({
                    "Task": task.task_name,
                    "Machine": machine,
                    "Start": task.start_time,
                    "Finish": task.end_time,
                    "Duration": task.duration,
                    "TaskType": type_name,
                    "TaskID": str(task.task_id),
                    "Job": job_name,
                    "IsSetup": False,
                })
                prev_task = task
        
        # Combine setup and task data
        all_data = setup_data + data
        
        # Create timeline using numeric x-axis (not datetime)
        color_col = "TaskType" if self.color_by == "task_type" else "Task"
        
        fig = self._create_numeric_gantt(all_data, title, color_col)
        
        # Update layout
        fig.update_layout(
            xaxis_title="Time (minutes)",
            yaxis_title="Machine",
            showlegend=True,
            legend_title=color_col,
            height=max(400, len(set(t["Machine"] for t in data)) * 80),
        )
        
        # Add metrics annotation box
        metrics_text = []
        if result.makespan is not None:
            metrics_text.append(f"Makespan: {result.makespan} min")
        if result.weighted_tardiness is not None:
            metrics_text.append(f"Weighted Tardiness: {result.weighted_tardiness}")
        if result.total_completion_time is not None:
            metrics_text.append(f"Total Completion Time: {result.total_completion_time} min")
        
        if metrics_text:
            fig.add_annotation(
                text="<br>".join(metrics_text),
                xref="paper", yref="paper",
                x=1, y=1.08,
                showarrow=False,
                font=dict(size=12, color="darkblue"),
                xanchor="right",
                align="right",
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="darkblue",
                borderwidth=1,
                borderpad=4
            )
        
        return fig
    
    def _create_numeric_gantt(
        self,
        data: List[Dict],
        title: str,
        color_col: str
    ) -> go.Figure:
        """
        Create Gantt chart with numeric time axis (minutes instead of datetime).
        
        Uses horizontal bar charts to create a Gantt-style visualization.
        Setup bars are rendered with diagonal stripe pattern.
        
        Args:
            data: List of task dictionaries with keys:
                  Task, Machine, Start, Finish, Duration, TaskType, TaskID, Job, IsSetup
            title: Chart title
            color_col: Column name to use for coloring bars ("TaskType" or "Task")
            
        Returns:
            Plotly Figure object with the Gantt chart
        """
        fig = go.Figure()
        
        # Get unique machines and colors
        machines = list(set(d["Machine"] for d in data))
        machines.sort()
        machine_to_y = {m: i for i, m in enumerate(machines)}
        
        # Color palette
        unique_colors = list(set(d[color_col] for d in data))
        color_map = {
            c: px.colors.qualitative.Plotly[i % len(px.colors.qualitative.Plotly)]
            for i, c in enumerate(unique_colors)
        }
        
        # Add bars
        for item in data:
            y = machine_to_y[item["Machine"]]
            is_setup = item.get("IsSetup", False)
            
            if is_setup:
                # Setup bar: gray with diagonal stripes
                marker_config = dict(
                    color="rgba(128, 128, 128, 0.6)",
                    pattern_shape="/",
                    pattern_fillmode="overlay",
                    line=dict(color="gray", width=1)
                )
            else:
                # Normal task bar
                color = color_map[item[color_col]]
                marker_config = dict(color=color)
            
            fig.add_trace(go.Bar(
                x=[item["Duration"]],
                y=[item["Machine"]],
                base=[item["Start"]],
                orientation="h",
                name=item[color_col],
                marker=marker_config,
                text=f"Setup:{item['Task'].replace('Setup→', '')}" if is_setup else item["Task"],
                textposition="inside",
                hovertemplate=(
                    f"<b>{item['Task']}</b><br>"
                    f"Job: {item['Job']}<br>"
                    f"Type: {item['TaskType']}<br>"
                    f"Machine: {item['Machine']}<br>"
                    f"Start: {item['Start']}<br>"
                    f"End: {item['Finish']}<br>"
                    f"Duration: {item['Duration']}<br>"
                    "<extra></extra>"
                ),
                showlegend=not is_setup and item[color_col] not in [t.name for t in fig.data],
            ))
        
        # Update layout
        fig.update_layout(
            title=title,
            barmode="overlay",
            xaxis=dict(title="Time (minutes)"),
            yaxis=dict(
                title="Machine",
                categoryorder="array",
                categoryarray=machines[::-1]
            ),
        )
        
        # Remove duplicate legends
        seen = set()
        for trace in fig.data:
            if trace.name in seen:
                trace.showlegend = False
            else:
                seen.add(trace.name)
        
        return fig
    
    def save_html(self, result: SolutionResult, file_path: str, **kwargs) -> None:
        """Save the Gantt chart as an HTML file."""
        fig = self.draw(result, **kwargs)
        fig.write_html(file_path)
    
    def save_image(
        self,
        result: SolutionResult,
        file_path: str,
        format: str = "png",
        **kwargs
    ) -> None:
        """Save the Gantt chart as an image file."""
        fig = self.draw(result, **kwargs)
        fig.write_image(file_path, format=format)
