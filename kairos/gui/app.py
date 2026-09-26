"""
Kairos Streamlit GUI Application.

A web interface for scheduling problems using three-field notation.
"""

import streamlit as st
import pandas as pd
from typing import List, Dict, Any

from kairos import (
    Task, Job, Machine, SchedulingProblem,
    SolverFactory, SolverType
)
from kairos.gui.notation_parser import NotationParser, SchedulingFeatures
from kairos.gui.solver_selector import SolverSelector
from kairos.visualization import GanttVisualizer



def main():
    """Main Streamlit application."""
    st.set_page_config(
        page_title="Kairos Scheduler",
        page_icon="⏱️",
        layout="wide"
    )
    
    st.title("⏱️ Kairos Scheduling Solver")
    st.markdown("Configure your scheduling problem using three-field notation (α|β|γ)")
    
    # Sidebar for notation selection
    with st.sidebar:
        st.header("📋 Problem Configuration")
        features = configure_notation()
        
        st.divider()
        st.markdown(f"**Notation:** `{features.get_notation()}`")
        
        solver_type = SolverSelector.get_solver_type(features)
        solver_name = SolverSelector.get_solver_name(solver_type)
        is_optimal = SolverSelector.is_optimal(solver_type, features)
        
        st.markdown(f"**Solver:** {solver_name}")
        if is_optimal:
            st.success("✅ Optimal algorithm")
        else:
            st.info("ℹ️ Heuristic/approximation")
    
    # Main content area
    tab1, tab2, tab3 = st.tabs(["📝 Data Entry", "📊 Results", "ℹ️ Help"])
    
    with tab1:
        problem = data_entry_tab(features)
        
        if problem and st.button("🚀 Solve", type="primary"):
            with st.spinner("Solving..."):
                result = solve_problem(problem, solver_type, features)
                st.session_state["result"] = result
                st.session_state["problem"] = problem
    
    with tab2:
        if "result" in st.session_state:
            display_results(st.session_state["result"], st.session_state["problem"])
        else:
            st.info("Configure your problem and click 'Solve' to see results.")
    
    with tab3:
        display_help()


def configure_notation() -> SchedulingFeatures:
    """Configure problem using three-field notation components."""
    
    # α - Machine environment
    machine_type = st.selectbox(
        "α (Machine Environment)",
        options=["1", "Pm", "Fm", "Jm"],
        format_func=lambda x: {
            "1": "1 - Single Machine",
            "Pm": "Pm - Parallel Identical Machines",
            "Fm": "Fm - Flow Shop",
            "Jm": "Jm - Job Shop",
        }.get(x, x),
        key="machine_type_select",
        on_change=lambda: st.session_state.pop("task_data", None)
    )
    
    num_machines = 1
    if machine_type in ("Pm", "Fm", "Jm"):
        num_machines = st.number_input("Number of Machines", min_value=1, max_value=100, value=2)
    
    # β - Constraints
    st.markdown("**β (Constraints)**")
    constraints = set()
    
    col1, col2 = st.columns(2)
    with col1:
        if st.checkbox("pmtn (Preemption)"):
            constraints.add("pmtn")
        if st.checkbox("rj (Release Times)"):
            constraints.add("rj")
        if st.checkbox("prec (Precedence)"):
            constraints.add("prec")
    with col2:
        if st.checkbox("sij (Setup Times)"):
            constraints.add("sij")
        if st.checkbox("dj (Due Dates)"):
            constraints.add("dj")
    
    # γ - Objective
    objective = st.selectbox(
        "γ (Objective)",
        options=["Cmax", "ΣCj", "ΣwjCj", "Lmax", "ΣTj"],
        format_func=lambda x: {
            "Cmax": "Cmax - Makespan",
            "ΣCj": "ΣCj - Total Completion Time",
            "ΣwjCj": "ΣwjCj - Weighted Completion Time",
            "Lmax": "Lmax - Maximum Lateness",
            "ΣTj": "ΣTj - Total Tardiness",
        }.get(x, x)
    )
    
    return NotationParser.from_components(
        machine_type=machine_type,
        constraints=constraints,
        objective=objective,
        num_machines=num_machines
    )


def data_entry_tab(features: SchedulingFeatures) -> SchedulingProblem:
    """Data entry UI based on features."""
    
    st.header("Enter Problem Data")
    
    # Data Source Selection
    data_source = st.radio("Data Source", ["Manual Entry", "Excel Upload"], horizontal=True)
    
    problem = None
    
    if data_source == "Excel Upload":
        uploaded_file = st.file_uploader("Upload Excel File", type=["xlsx", "xls"])
        
        if uploaded_file is not None:
            try:
                import tempfile
                import os
                from kairos.data.excel_loader import ExcelDataLoader
                
                # Save uploaded file to temp file
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_path = tmp_file.name
                
                # Load problem
                loader = ExcelDataLoader()
                problem = loader.load_problem(tmp_path, problem_name="Uploaded Problem")
                
                # Clean up temp file
                os.unlink(tmp_path)
                
                # Apply sidebar settings to loaded problem
                if features.preemption:
                    problem.enable_preemption()
                
                # Display success info
                st.success(f"✅ Loaded {len(problem.tasks)} tasks and {len(problem.machines)} machines.")
                
                # Show loaded data preview
                if problem.tasks:
                    task_data = []
                    for t in problem.tasks:
                        task_data.append({
                            "ID": t.id,
                            "Name": t.name,
                            "Job": t.job.name if t.job else "-",
                            "Duration": list(t.alternatives.values())[0] if t.alternatives else 0
                        })
                    st.dataframe(pd.DataFrame(task_data), use_container_width=True)
                    
            except Exception as e:
                st.error(f"Error loading file: {e}")
                return None
        else:
            st.info("📂 Upload an Excel file with Machines, Jobs, and Tasks sheets.")
        
        return problem
    
    # Manual Entry Logic
    problem = SchedulingProblem(name="GUI Problem")
    
    # Enable preemption if needed
    if features.preemption:
        problem.enable_preemption()
    
    # Machines
    st.subheader("🔧 Machines")
    num_machines = features.num_machines if features.num_machines > 0 else st.session_state.get("num_machines", 1)
    
    for i in range(num_machines):
        machine = Machine(id=i+1, name=f"M{i+1}")
        problem.add_machine(machine)
    
    st.info(f"{num_machines} machine(s) configured")
    
    # Job/Task data editor
    st.subheader("📦 Jobs / Tasks")
    
    # Determine which columns to show
    columns = ["Name"]
    
    # For Flow/Job/Unrelated shops, we need processing time per machine
    # In Flow Shop (Fm), rows are Jobs, columns are Machines.
    # In Job Shop (Jm), user inputs sequence of machines and durations.
    is_matrix_input = features.machine_type in ("Fm", "Qm", "Om")
    is_job_shop = features.machine_type == "Jm"
    
    if is_job_shop:
        columns.append("Machines")
        columns.append("Durations")
    elif is_matrix_input:
        for i in range(num_machines):
            columns.append(f"M{i+1}")
    else:
        # Standard input (identical machines or single machine)
        columns.append("Duration")
    
    if features.release_times:
        columns.append("Release Time")
    if features.due_dates:
        columns.append("Due Date")
    if features.objective in ("ΣwjCj", "ΣwjTj"):
        columns.append("Weight")
    
    # Task data editor
    if "task_data" not in st.session_state:
        # Initial data structure depends on type
        # For Fm/Jm, default names are Job1, Job2... For others Task1, Task2...
        prefix = "Job" if features.machine_type in ("Fm", "Jm") else "Task"
        initial_data = {"Name": [f"{prefix}1", f"{prefix}2", f"{prefix}3"]}
        
        if is_job_shop:
            # Example data for Job Shop (classical 3x3 example)
            initial_data["Machines"] = ["1,2,3", "2,3,1", "3,1,2"]
            initial_data["Durations"] = ["10,20,15", "15,10,12", "12,15,10"]
        elif is_matrix_input:
            for i in range(num_machines):
                initial_data[f"M{i+1}"] = [10 + i*5, 20 + i*5, 15 + i*5]
        else:
            initial_data["Duration"] = [10, 20, 15]
            
        initial_data["Release Time"] = [0, 0, 0]
        initial_data["Due Date"] = [50, 60, 55]
        initial_data["Weight"] = [1, 1, 1]
        
        st.session_state["task_data"] = pd.DataFrame(initial_data)
    
    # Ensure all machine columns exist if number of machines changed (for matrix input)
    if is_matrix_input:
        for i in range(num_machines):
            col_name = f"M{i+1}"
            if col_name not in st.session_state["task_data"].columns:
                st.session_state["task_data"][col_name] = 10  # Default value
    
    # Filter columns based on features
    visible_columns = [c for c in columns if c in st.session_state["task_data"].columns]
    
    edited_df = st.data_editor(
        st.session_state["task_data"][visible_columns],
        num_rows="dynamic",
        use_container_width=True
    )
    
    # Update session state
    for col in visible_columns:
        st.session_state["task_data"][col] = edited_df[col]
    
    # Create problem components based on input
    for idx, row in edited_df.iterrows():
        # Common attributes
        release_time = int(row.get("Release Time", 0)) if "Release Time" in row else 0
        due_date = int(row.get("Due Date", 0)) if "Due Date" in row else None
        weight = int(row.get("Weight", 1)) if "Weight" in row else 1
        name = row["Name"]
        
        if features.machine_type == "Fm":
            # Flow Shop: Fixed sequence M1 -> M2 -> ... -> Mm
            # Rows are Jobs, columns are Machines (M1, M2...)
            job = Job(id=f"J{idx+1}", name=name, due_date=due_date, priority=weight)
            previous_task = None
            
            for i in range(num_machines):
                col_name = f"M{i+1}"
                duration = int(row.get(col_name, 0))
                
                # Create a task for this operation
                task = Task(
                    id=f"{idx+1}_{i+1}", 
                    name=f"{name}_M{i+1}",
                    release_time=release_time if i == 0 else 0 
                )
                
                # Assign to specific machine
                task.add_alternative(i + 1, duration)
                
                if previous_task:
                    task.add_predecessor(previous_task)
                
                job.add_task(task)
                problem.add_task(task)
                previous_task = task
                
            problem.add_job(job)
            
        elif features.machine_type == "Jm":
            # Job Shop: User defines sequence of machines and durations
            # Expected columns: "Machines" (e.g. "1,3,2"), "Durations" (e.g. "10,15,12")
            job = Job(id=f"J{idx+1}", name=name, due_date=due_date, priority=weight)
            
            # Parse machine sequence
            m_seq_str = str(row.get("Machines", "")).strip()
            d_seq_str = str(row.get("Durations", "")).strip()
            
            try:
                # Convert comma-separated string to list
                machine_ids = []
                if m_seq_str:
                    machine_ids = [int(m.strip()) for m in m_seq_str.split(",") if m.strip()]
                
                durations = []
                if d_seq_str:
                    durations = [int(d.strip()) for d in d_seq_str.split(",") if d.strip()]
                
                if len(machine_ids) != len(durations):
                    st.warning(f"Job {name}: Mismatch between Machines ({len(machine_ids)}) and Durations ({len(durations)}). Using shortest length.")
                    min_len = min(len(machine_ids), len(durations))
                    machine_ids = machine_ids[:min_len]
                    durations = durations[:min_len]
                
                previous_task = None
                for i, (m_id, dur) in enumerate(zip(machine_ids, durations)):
                    # Validate machine ID
                    if m_id not in problem.machines:
                        st.error(f"Job {name}: Machine ID {m_id} does not exist.")
                        continue
                        
                    task = Task(
                        id=f"{idx+1}_{i+1}",
                        name=f"{name}_Op{i+1}_M{m_id}",
                        release_time=release_time if i == 0 else 0
                    )
                    
                    task.add_alternative(m_id, dur)
                    
                    if previous_task:
                        task.add_predecessor(previous_task)
                        
                    job.add_task(task)
                    problem.add_task(task)
                    previous_task = task
                    
                problem.add_job(job)
                
            except ValueError as e:
                st.error(f"Error parsing Job {name}: {e}. Use format '1,2,3'")

        elif is_matrix_input:
            # Qm/Om: Treating row as a Task with specific processing times matrix
            task = Task(id=idx+1, name=name, release_time=release_time)
            
            for i in range(num_machines):
                col_name = f"M{i+1}"
                if col_name in row:
                    machine_id = i + 1
                    task.add_alternative(machine_id, int(row[col_name]))
            
            if due_date or weight > 1:
                job = Job(id=f"J{idx+1}", name=f"Job{idx+1}", due_date=due_date, priority=weight)
                job.add_task(task)
                problem.add_job(job)
            else:
                problem.add_task(task)
                
        else:
            # Standard Single/Parallel Machines
            task = Task(id=idx+1, name=name, release_time=release_time)
            duration = int(row["Duration"])
            for machine in problem.machines.values():
                task.add_alternative(machine.id, duration)
            
            if due_date or weight > 1:
                job = Job(id=f"J{idx+1}", name=f"Job{idx+1}", due_date=due_date, priority=weight)
                job.add_task(task)
                problem.add_job(job)
            else:
                problem.add_task(task)
    
    return problem
    
    return problem


def solve_problem(problem: SchedulingProblem, solver_type: SolverType, features: SchedulingFeatures):
    """Solve the scheduling problem."""
    solver = SolverFactory.get_solver(solver_type)
    result = solver.solve(problem)
    return result


def display_results(result, problem):
    """Display solution results."""
    st.header("📊 Solution Results")
    
    # Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Status", result.status)
    with col2:
        val = result.makespan
        st.metric("Makespan", f"{val:.1f}" if val is not None else "N/A")
    with col3:
        val = result.total_completion_time
        st.metric("Total Completion", f"{val:.1f}" if val is not None else "N/A")
    with col4:
        st.metric("Solve Time", f"{val:.3f}s" if val is not None else "N/A")
    
    if result.status not in ("OPTIMAL", "FEASIBLE"):
        if result.message:
            st.error(f"Solver Message: {result.message}")
        
        if result.status == "INCOMPATIBLE":
             st.info("💡 Hint: Your sidebar 'Problem Configuration' matches a different problem type than your loaded Excel data. Please update the Sidebar (e.g., select 'Pm' or 'Jm') to match your file.")
    
    # Gantt chart
    st.subheader("📈 Gantt Chart")
    try:
        viz = GanttVisualizer()
        fig = viz.draw(result)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Could not render Gantt chart: {e}")
    
    # Schedule table
    st.subheader("📋 Schedule Details")
    schedule_data = []
    for s in result.schedule:
        schedule_data.append({
            "Task": s.task_name,
            "Machine": s.machine.name,
            "Start": s.start_time,
            "End": s.end_time,
            "Duration": s.duration,
        })
    
    st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)


def display_help():
    """Display help information."""
    st.header("ℹ️ Three-Field Notation Guide")
    
    st.markdown("""
    ### α - Machine Environment
    - **1**: Single machine
    - **Pm**: m identical parallel machines
    - **Fm**: Flow shop (tasks must visit machines in order)
    - **Jm**: Job shop (each job has its own machine route)
    
    ### β - Constraints
    - **pmtn**: Tasks can be preempted (interrupted and resumed)
    - **rj**: Tasks have release times (not available at t=0)
    - **prec**: Precedence constraints between tasks
    - **sij**: Sequence-dependent setup times
    - **dj**: Tasks have due dates
    
    ### γ - Objective
    - **Cmax**: Minimize makespan (total schedule length)
    - **ΣCj**: Minimize total completion time
    - **ΣwjCj**: Minimize weighted completion time
    - **Lmax**: Minimize maximum lateness
    - **ΣTj**: Minimize total tardiness
    
    ### Examples
    - `1 || Cmax` - Single machine, minimize makespan
    - `Pm | pmtn | Cmax` - Parallel machines with preemption, minimize makespan
    - `1 | rj | ΣCj` - Single machine with release times, minimize total completion
    """)


if __name__ == "__main__":
    main()
