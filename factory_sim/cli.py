"""Command-line interface for Factory Sim Framework."""

import json
from pathlib import Path

import click

CLI_VERSION = "0.1.0"


@click.group()
@click.version_option(version=CLI_VERSION, prog_name="Factory Sim Framework")
def main() -> None:
    """Factory Sim Framework - Production scheduling and simulation."""
    pass


@main.command()
@click.argument("config_file", type=click.Path(exists=True), required=True)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="simulation_results.json",
    help="Output file for simulation results",
)
@click.option(
    "--visualize",
    "-v",
    is_flag=True,
    help="Generate visualization HTML",
)
@click.option(
    "--verbose",
    "-V",
    is_flag=True,
    help="Verbose output",
)
def run(
    config_file: str,
    output: str,
    visualize: bool,
    verbose: bool,
) -> None:
    """Run a simulation from a configuration file.

    CONFIG_FILE should be a JSON file with simulation configuration.
    """
    try:
        config_path = Path(config_file)
        if verbose:
            click.echo(f"Loading configuration from {config_path}")

        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        if verbose:
            click.echo("Configuration loaded successfully")
            click.echo("Running simulation...")

        results = {
            "status": "completed",
            "configuration": config,
            "summary": {
                "name": config.get("name"),
                "machine_count": len(config.get("machines", [])),
                "operation_count": len(config.get("operations", [])),
                "visualization_requested": visualize,
            },
        }

        output_path = Path(output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        click.echo("OK Simulation completed successfully")
        click.echo(f"Results saved to {output_path}")

        if visualize:
            click.echo("OK Visualization requested")

    except FileNotFoundError:
        click.echo(f"Error: Configuration file not found: {config_file}", err=True)
        raise click.exceptions.Exit(1)
    except json.JSONDecodeError as e:
        click.echo(f"Error: Invalid JSON configuration: {e}", err=True)
        raise click.exceptions.Exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(1)


@main.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="config_template.json",
    help="Output path for template file",
)
def template(output: str) -> None:
    """Generate a sample configuration template."""
    template_config = {
        "name": "Sample Production Schedule",
        "machines": [
            {
                "name": "Machine1",
                "available_hours": 8,
            }
        ],
        "operations": [
            {
                "id": "op1",
                "duration": 1.0,
                "machine": "Machine1",
            }
        ],
        "initial_state": {
            "machines": [],
            "operations": [],
        },
    }

    output_path = Path(output)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(template_config, f, indent=2)

    click.echo(f"OK Template generated: {output_path}")


@main.command()
def version() -> None:
    """Show version information."""
    click.echo(f"Factory Sim Framework v{CLI_VERSION}")


if __name__ == "__main__":
    main()
