"""
Dependency graph visualization for scheduling problems.

Creates an assembly chart showing task predecessor relationships
with tasks grouped by their parent Job.
"""

from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

import plotly.graph_objects as go


class DependencyGraphVisualizer:
    """
    Create assembly/dependency graph visualizations showing task relationships.
    
    Features:
    - Circular nodes for tasks
    - Tasks grouped by parent Job with bounding boxes
    - Identical jobs (batches) shown once with batch count
    - Due date and priority displayed per job group
    """
    
    def __init__(self):
        # Layout settings
        self.node_radius = 0.7    # Circle radius
        self.h_spacing = 4.5      # Horizontal space between layers
        self.v_spacing = 2.5      # Vertical space between nodes
        self.job_padding = 1.0    # Padding around job groups
        
        # Colors
        self.colors = {
            "nodes": [
                "#3b82f6",  # Blue
                "#8b5cf6",  # Purple
                "#10b981",  # Green
                "#f59e0b",  # Amber
                "#ef4444",  # Red
                "#06b6d4",  # Cyan
                "#ec4899",  # Pink
                "#6366f1",  # Indigo
            ],
            "job_borders": [
                "#3b82f6",  # Blue
                "#8b5cf6",  # Purple  
                "#10b981",  # Green
                "#f59e0b",  # Amber
            ],
            "job_fills": [
                "rgba(59, 130, 246, 0.08)",  # Blue
                "rgba(139, 92, 246, 0.08)",  # Purple
                "rgba(16, 185, 129, 0.08)",  # Green
                "rgba(245, 158, 11, 0.08)",  # Amber
            ],
            "edge": "#94a3b8",
            "arrow": "#475569",
            "bg": "#f8fafc",
            "text": "#1e293b",
            "text_secondary": "#64748b",
            "text_white": "#ffffff",
        }
    
    def draw(self, problem, title: str = "BOM / Task Dependencies") -> go.Figure:
        """Create a dependency graph from a scheduling problem."""
        if not problem.jobs and not problem.tasks:
            return self._empty_figure(title)
        
        # Group identical jobs (batches) by structure
        job_groups = self._group_identical_jobs(problem.jobs)
        
        # Get standalone tasks (not in any job)
        standalone_tasks = [t for t in problem.tasks if t.job is None]
        
        # Calculate positions for all tasks
        positions = self._calculate_positions(job_groups, standalone_tasks)
        
        fig = go.Figure()
        
        # Draw job bounding boxes first (behind everything)
        self._draw_job_boxes(fig, job_groups, positions)
        
        # Draw edges
        self._draw_edges(fig, problem.tasks, positions)
        
        # Draw circular nodes
        self._draw_nodes(fig, problem.tasks, positions)
        
        self._configure_layout(fig, title, positions)
        
        return fig
    
    def _empty_figure(self, title: str) -> go.Figure:
        """Create an empty figure with 'No tasks' message."""
        fig = go.Figure()
        fig.add_annotation(
            text="No tasks to display",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=18, color=self.colors["text"])
        )
        fig.update_layout(title=title, plot_bgcolor=self.colors["bg"])
        return fig
    
    def _group_identical_jobs(self, jobs: List) -> List[dict]:
        """
        Group identical jobs (same name, due_date, priority) together.
        Returns list of {"job": Job, "count": int, "tasks": List[Task]}
        """
        if not jobs:
            return []
        
        # Group by (name, due_date, priority) - all must match for batching
        groups = defaultdict(list)
        for job in jobs:
            key = (job.name, job.due_date, job.priority)
            groups[key].append(job)
        
        result = []
        for key, job_list in groups.items():
            # Use first job as representative
            rep_job = job_list[0]
            result.append({
                "job": rep_job,
                "count": len(job_list),
                "tasks": rep_job.tasks,  # Use representative's tasks
            })
        
        return result
    
    def _calculate_positions(self, job_groups: List[dict], standalone_tasks: List) -> Dict:
        """
        Calculate node positions using topological layering.
        
        Groups tasks by parent job, orders by dependency depth within each group.
        
        Args:
            job_groups: List of job group dicts with 'job', 'count', 'tasks' keys
            standalone_tasks: Tasks not belonging to any job
            
        Returns:
            Dict mapping task_id to (x, y) position tuple
        """
        positions = {}
        
        # Collect all tasks
        all_tasks = []
        for group in job_groups:
            all_tasks.extend(group["tasks"])
        all_tasks.extend(standalone_tasks)
        
        if not all_tasks:
            return positions
        
        task_map = {t.id: t for t in all_tasks}
        
        # Calculate layers based on predecessors
        layers = {}
        
        def get_layer(task_id: int, visited: Set[int]) -> int:
            if task_id in layers:
                return layers[task_id]
            if task_id in visited:
                return 0
            
            visited.add(task_id)
            task = task_map.get(task_id)
            
            if not task or not task.predecessors:
                layers[task_id] = 0
                return 0
            
            max_pred_layer = 0
            for pred in task.predecessors:
                if pred.id in task_map:
                    max_pred_layer = max(max_pred_layer, get_layer(pred.id, visited.copy()))
            
            layers[task_id] = max_pred_layer + 1
            return layers[task_id]
        
        for task in all_tasks:
            get_layer(task.id, set())
        
        # Position jobs vertically, tasks within each job by layer
        current_y = 0
        
        for group_idx, group in enumerate(job_groups):
            job_tasks = group["tasks"]
            if not job_tasks:
                continue
            
            # Group tasks by layer within this job
            by_layer: Dict[int, List] = {}
            for task in job_tasks:
                layer = layers.get(task.id, 0)
                by_layer.setdefault(layer, []).append(task)
            
            # Sort tasks alphabetically within each layer
            for layer in by_layer:
                by_layer[layer].sort(key=lambda t: t.name)
            
            # Calculate height needed for this job
            max_tasks_per_layer = max(len(tasks) for tasks in by_layer.values()) if by_layer else 1
            job_height = max_tasks_per_layer * self.v_spacing
            
            # Position tasks
            job_start_y = current_y
            for layer, layer_tasks in sorted(by_layer.items()):
                n = len(layer_tasks)
                for i, task in enumerate(layer_tasks):
                    x = layer * self.h_spacing
                    y = job_start_y - (i - (n - 1) / 2) * self.v_spacing
                    positions[task.id] = (x, y)
            
            current_y -= job_height + 4.0  # Space between jobs
        
        # Position standalone tasks
        if standalone_tasks:
            by_layer: Dict[int, List] = {}
            for task in standalone_tasks:
                layer = layers.get(task.id, 0)
                by_layer.setdefault(layer, []).append(task)
            
            for layer, layer_tasks in sorted(by_layer.items()):
                n = len(layer_tasks)
                for i, task in enumerate(layer_tasks):
                    x = layer * self.h_spacing
                    y = current_y - (i - (n - 1) / 2) * self.v_spacing
                    positions[task.id] = (x, y)
        
        return positions
    
    def _draw_job_boxes(self, fig: go.Figure, job_groups: List[dict], positions: Dict) -> None:
        """
        Draw bounding boxes around each job group.
        
        Includes job name, batch count (if > 1), due date, and priority.
        """
        for idx, group in enumerate(job_groups):
            job = group["job"]
            count = group["count"]
            tasks = group["tasks"]
            
            if not tasks:
                continue
            
            # Get bounding box of all tasks in this job
            task_positions = [positions.get(t.id) for t in tasks if t.id in positions]
            if not task_positions:
                continue
            
            xs = [p[0] for p in task_positions]
            ys = [p[1] for p in task_positions]
            
            pad = self.job_padding
            x0, x1 = min(xs) - self.node_radius - pad, max(xs) + self.node_radius + pad
            y0, y1 = min(ys) - self.node_radius - pad, max(ys) + self.node_radius + pad + 0.8
            
            border_color = self.colors["job_borders"][idx % len(self.colors["job_borders"])]
            fill_color = self.colors["job_fills"][idx % len(self.colors["job_fills"])]
            
            # Draw rounded rectangle for job
            fig.add_shape(
                type="rect",
                x0=x0, y0=y0,
                x1=x1, y1=y1,
                fillcolor=fill_color,
                line=dict(width=2, color=border_color, dash="solid"),
                layer="below",
            )
            
            # Job label at top of box
            # Format: "Job Name (x3)  |  Due: 200  |  Priority: 2"
            label_parts = [f"<b>{job.name}</b>"]
            if count > 1:
                label_parts[0] += f" <b>×{count}</b>"
            
            if job.due_date is not None:
                label_parts.append(f"Due: {job.due_date}")
            if job.priority and job.priority > 1:
                label_parts.append(f"Priority: {job.priority}")
            
            label = "  |  ".join(label_parts)
            
            fig.add_annotation(
                x=(x0 + x1) / 2, y=y1 - 0.3,
                text=label,
                showarrow=False,
                font=dict(size=11, color=border_color, family="Arial"),
                xanchor="center", yanchor="top",
            )
    
    def _draw_edges(self, fig: go.Figure, tasks: List, positions: Dict) -> None:
        """Draw connecting lines between predecessor and successor tasks."""
        for task in tasks:
            if task.id not in positions:
                continue
            
            tx, ty = positions[task.id]
            
            for pred in task.predecessors:
                if pred.id not in positions:
                    continue
                
                px, py = positions[pred.id]
                
                # Start from right side of predecessor circle
                start_x = px + self.node_radius
                start_y = py
                
                # End at left side of successor circle
                end_x = tx - self.node_radius
                end_y = ty
                
                # Draw line
                fig.add_trace(go.Scatter(
                    x=[start_x, end_x - 0.12],
                    y=[start_y, end_y],
                    mode='lines',
                    line=dict(width=2, color=self.colors["edge"]),
                    hoverinfo='none',
                    showlegend=False,
                ))
                
                # Arrow at destination
                fig.add_annotation(
                    x=end_x, y=end_y,
                    ax=end_x - 0.2, ay=end_y,
                    xref='x', yref='y', axref='x', ayref='y',
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=1.2,
                    arrowwidth=2,
                    arrowcolor=self.colors["arrow"],
                )
    
    def _draw_nodes(self, fig: go.Figure, tasks: List, positions: Dict) -> None:
        """
        Draw task nodes as colored circles with labels and hover info.
        
        Node color is determined by task_type. Includes duration and full name labels.
        """
        type_colors = {}
        
        for task in tasks:
            if task.id not in positions:
                continue
            
            x, y = positions[task.id]
            task_type = task.get_effective_task_type() if hasattr(task, 'get_effective_task_type') else task.task_type
            
            # Assign color by task type
            type_key = str(task_type)
            if type_key not in type_colors:
                type_colors[type_key] = self.colors["nodes"][len(type_colors) % len(self.colors["nodes"])]
            
            color = type_colors[type_key]
            
            # Draw circular node
            fig.add_shape(
                type="circle",
                x0=x - self.node_radius, y0=y - self.node_radius,
                x1=x + self.node_radius, y1=y + self.node_radius,
                fillcolor=color,
                line=dict(width=2, color="white"),
                layer="above",
            )
            
            # Get task info
            machines = list(task.alternatives.keys()) if task.alternatives else []
            duration = task.alternatives[machines[0]] if machines else "?"
            
            # Short name for circle
            short_name = self._make_short_name(task.name)
            
            # Task short name inside circle
            fig.add_annotation(
                x=x, y=y + 0.05,
                text=f"<b>{short_name}</b>",
                showarrow=False,
                font=dict(size=10, color=self.colors["text_white"], family="Arial"),
                xanchor="center", yanchor="middle",
            )
            
            # Duration below short name
            fig.add_annotation(
                x=x, y=y - 0.25,
                text=f"t={duration}",
                showarrow=False,
                font=dict(size=8, color="rgba(255,255,255,0.8)", family="Arial"),
                xanchor="center", yanchor="middle",
            )
            
            # Full task name below circle
            fig.add_annotation(
                x=x, y=y - self.node_radius - 0.25,
                text=task.name,
                showarrow=False,
                font=dict(size=9, color=self.colors["text_secondary"], family="Arial"),
                xanchor="center", yanchor="top",
            )
            
            # Hover template
            preds_list = ", ".join([p.name for p in task.predecessors]) if task.predecessors else "None"
            machines_list = ", ".join([f"M{m}" for m in machines]) if machines else "None"
            job_info = f"Job: {task.job.name}" if task.job else "Standalone"
            
            hover = (
                f"<b>{task.name}</b><br>"
                f"{job_info}<br>"
                f"Type: {task_type}<br>"
                f"Duration: {duration}<br>"
                f"Machines: {machines_list}<br>"
                f"Predecessors: {preds_list}"
            )
            
            # Invisible scatter for hover
            fig.add_trace(go.Scatter(
                x=[x], y=[y],
                mode='markers',
                marker=dict(size=50, color='rgba(0,0,0,0)'),
                hovertemplate=hover + '<extra></extra>',
                showlegend=False,
            ))
    
    def _make_short_name(self, name: str, max_len: int = 8) -> str:
        """Create abbreviated name for circle display."""
        parts = name.replace('-', '_').split('_')
        if len(parts) >= 2:
            # Take first letter of each part
            abbrev = ''.join(p[0].upper() for p in parts if p)
            if len(abbrev) <= max_len:
                return abbrev
        return name[:max_len] if len(name) > max_len else name
    
    def _configure_layout(self, fig: go.Figure, title: str, positions: Dict) -> None:
        """
        Configure chart layout, axes, and add flow direction indicator.
        
        Sets axis ranges based on node positions with appropriate padding.
        """
        if positions:
            xs = [p[0] for p in positions.values()]
            ys = [p[1] for p in positions.values()]
            
            x_pad = 3.0
            y_pad = 2.5
            x_range = [min(xs) - x_pad, max(xs) + x_pad]
            y_range = [min(ys) - y_pad, max(ys) + y_pad]
        else:
            x_range, y_range = [-1, 1], [-1, 1]
        
        fig.update_layout(
            title=dict(
                text=f"<b>{title}</b>",
                font=dict(size=18, color=self.colors["text"]),
                x=0.5,
            ),
            showlegend=False,
            hovermode='closest',
            xaxis=dict(
                showgrid=False, zeroline=False, showticklabels=False,
                range=x_range, fixedrange=True,
            ),
            yaxis=dict(
                showgrid=False, zeroline=False, showticklabels=False,
                range=y_range, scaleanchor='x', fixedrange=True,
            ),
            plot_bgcolor=self.colors["bg"],
            paper_bgcolor="white",
            height=600,
            margin=dict(l=40, r=40, t=70, b=50),
        )
        
        # Flow direction indicator
        fig.add_annotation(
            text="◀ Start  ───────  Finish ▶",
            xref="paper", yref="paper", x=0.5, y=-0.03,
            showarrow=False, 
            font=dict(size=11, color=self.colors["text_secondary"]),
        )
    
    def save_html(self, problem, file_path: str, **kwargs) -> None:
        """Save the graph to an HTML file."""
        fig = self.draw(problem, **kwargs)
        fig.write_html(file_path, include_plotlyjs='cdn')
