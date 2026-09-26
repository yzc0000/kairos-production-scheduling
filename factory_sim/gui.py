"""Web-based GUI for Factory Sim Framework using Streamlit."""

import json
from pathlib import Path
from typing import Optional

import streamlit as st

st.set_page_config(
    page_title="Factory Sim Framework",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    """Main Streamlit application."""
    st.title("🏭 Factory Sim Framework")
    st.markdown(
        "Production scheduling and simulation validation for multi-stage systems"
    )

    # Sidebar navigation
    page = st.sidebar.radio(
        "Navigation",
        [
            "📊 Dashboard",
            "🚀 Run Simulation",
            "📋 Configuration",
            "📈 Results",
            "ℹ️ About",
        ],
    )

    if page == "📊 Dashboard":
        show_dashboard()
    elif page == "🚀 Run Simulation":
        show_run_simulation()
    elif page == "📋 Configuration":
        show_configuration()
    elif page == "📈 Results":
        show_results()
    elif page == "ℹ️ About":
        show_about()


def show_dashboard() -> None:
    """Dashboard page."""
    st.header("Dashboard")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Simulations", "0", "")
    with col2:
        st.metric("Average Runtime", "0s", "")
    with col3:
        st.metric("Success Rate", "0%", "")

    st.markdown("---")
    st.subheader("Recent Simulations")
    st.info("No simulations yet. Start by running a new simulation!")


def show_run_simulation() -> None:
    """Run Simulation page."""
    st.header("Run Simulation")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Configuration")
        config_source = st.radio(
            "Configuration source:",
            ["Upload File", "Create New"],
            horizontal=True,
        )

        if config_source == "Upload File":
            uploaded_file = st.file_uploader(
                "Upload configuration file (JSON)",
                type=["json"],
            )
            if uploaded_file:
                st.success("File uploaded successfully!")
        else:
            st.text_area(
                "Configuration (JSON)",
                value='{\n  "name": "My Simulation"\n}',
                height=200,
            )

    with col2:
        st.subheader("Simulation Parameters")
        num_runs = st.number_input(
            "Number of simulation runs",
            min_value=1,
            max_value=100,
            value=1,
        )
        random_seed = st.checkbox("Use random seed", value=False)
        if random_seed:
            st.number_input("Seed value", value=42)

    st.markdown("---")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("▶️ Run Simulation", use_container_width=True):
            with st.spinner("Running simulation..."):
                st.success("Simulation completed!")
    with col2:
        if st.button("📥 Load Template", use_container_width=True):
            st.info("Template loaded")


def show_configuration() -> None:
    """Configuration page."""
    st.header("Configuration Management")

    tab1, tab2, tab3 = st.tabs(["Create", "Edit", "Templates"])

    with tab1:
        st.subheader("Create New Configuration")
        config_name = st.text_input("Configuration name")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Machines")
            if st.button("➕ Add Machine"):
                st.info("Machine added")

        with col2:
            st.subheader("Operations")
            if st.button("➕ Add Operation"):
                st.info("Operation added")

    with tab2:
        st.subheader("Edit Existing Configuration")
        st.file_uploader("Select configuration to edit", type=["json"])

    with tab3:
        st.subheader("Configuration Templates")
        st.info("No templates available yet")


def show_results() -> None:
    """Results page."""
    st.header("Simulation Results")

    col1, col2 = st.columns([1, 3])

    with col1:
        st.subheader("Filters")
        st.date_input("From date")
        st.date_input("To date")
        if st.button("Search"):
            st.info("Searching results...")

    with col2:
        st.subheader("Results")
        st.info(
            "No results yet. Run a simulation to see results here."
        )


def show_about() -> None:
    """About page."""
    st.header("About Kairos")

    st.markdown(
        """
    **Kairos** combines job-shop scheduling with simulation-based validation
    for multi-stage production systems.

    ### Features
    - 🎯 Constraint-based scheduling
    - 🔄 Stochastic simulation
    - 📊 Interactive visualization
    - 💾 Configuration management
    - 🚀 Web-based and CLI interfaces

    Source code and usage instructions are available in the project README.

    ### Version
    """
    )
    st.code("0.1.0", language="plaintext")


if __name__ == "__main__":
    main()
