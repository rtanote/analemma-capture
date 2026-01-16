"""Command-line interface for Analemma Capture System."""

import json
from pathlib import Path
from typing import Optional

import click
import yaml

from analemma import __version__
from analemma.camera import CameraController, CameraError, list_cameras
from analemma.config import Config, load_config
from analemma.logger import setup_logger
from analemma.main import AnalemmaSystem


@click.group()
@click.version_option(version=__version__, prog_name="analemma")
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    help="Path to configuration file",
)
@click.pass_context
def cli(ctx: click.Context, config_path: Optional[Path]) -> None:
    """Analemma Solar Capture System.

    Automated solar photography for capturing the analemma pattern.
    """
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


@cli.command()
@click.pass_context
def capture(ctx: click.Context) -> None:
    """Capture an image immediately."""
    config_path = ctx.obj.get("config_path")
    config = load_config(config_path)
    setup_logger(config.logging)

    click.echo("Starting capture...")

    system = AnalemmaSystem(config)
    result = system.capture_workflow()

    if result:
        click.echo(f"Capture successful!")
        click.echo(f"  Image saved to: {result}")

        # Show image info
        status = system.get_status()
        click.echo(f"  Consecutive successes: {status['capture']['consecutive_successes']}")
    else:
        click.echo("Capture failed. Check logs for details.", err=True)
        ctx.exit(1)


@cli.command("camera-info")
@click.pass_context
def camera_info(ctx: click.Context) -> None:
    """Display connected camera information."""
    config_path = ctx.obj.get("config_path")
    config = load_config(config_path)

    click.echo("Searching for ZWO ASI cameras...")

    cameras = list_cameras()

    if not cameras:
        click.echo("No ZWO ASI cameras found.", err=True)
        click.echo("\nTroubleshooting tips:")
        click.echo("  1. Ensure the camera is connected via USB")
        click.echo("  2. Check udev rules are installed (see README)")
        click.echo("  3. Try unplugging and reconnecting the camera")
        ctx.exit(1)

    click.echo(f"\nFound {len(cameras)} camera(s):\n")

    for cam in cameras:
        click.echo(f"  [{cam['index']}] {cam['name']}")
        click.echo(f"      Resolution: {cam['max_resolution']}")
        click.echo(f"      Color: {'Yes' if cam['is_color'] else 'No'}")

    # Get detailed info for first camera
    click.echo("\nDetailed info for camera 0:")
    try:
        controller = CameraController(config.camera, camera_index=0)
        controller.connect()
        info = controller.get_info()
        controller.disconnect()

        click.echo(f"  Model: {info.name}")
        click.echo(f"  Max Resolution: {info.max_width}x{info.max_height}")
        click.echo(f"  Color: {'Yes' if info.is_color else 'No'}")
        if info.bayer_pattern:
            click.echo(f"  Bayer Pattern: {info.bayer_pattern}")
        click.echo(f"  Pixel Size: {info.pixel_size}um")
        click.echo(f"  Bit Depth: {info.bit_depth}")
        click.echo(f"  USB3: {'Yes' if info.is_usb3 else 'No'}")
        click.echo(f"  Supported Bins: {info.supported_bins}")

    except CameraError as e:
        click.echo(f"  Error getting detailed info: {e}", err=True)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Display system status."""
    config_path = ctx.obj.get("config_path")
    config = load_config(config_path)

    system = AnalemmaSystem(config)
    status_info = system.get_status()

    click.echo("=== Analemma System Status ===\n")

    # Schedule info
    click.echo("Schedule:")
    click.echo(f"  Capture time: {status_info['schedule']['capture_time']}")
    if status_info['schedule'].get('next_capture'):
        click.echo(f"  Next capture: {status_info['schedule']['next_capture']}")

    # Capture stats
    click.echo("\nCapture Statistics:")
    click.echo(
        f"  Consecutive successes: {status_info['capture']['consecutive_successes']}"
    )
    if status_info['capture']['last_capture_time']:
        click.echo(f"  Last capture: {status_info['capture']['last_capture_time']}")
        click.echo(f"  Last file: {status_info['capture']['last_capture_path']}")
    else:
        click.echo("  No captures recorded yet")

    # Storage info
    click.echo("\nStorage:")
    click.echo(f"  Path: {status_info['storage']['base_path']}")
    click.echo(
        f"  Free space: {status_info['storage']['free_gb']:.2f} GB / "
        f"{status_info['storage']['total_gb']:.2f} GB"
    )
    click.echo(f"  Image count: {status_info['storage']['image_count']}")

    # Check for low storage warning
    if status_info['storage']['free_gb'] < config.storage.min_free_space_mb / 1024:
        click.echo(
            f"\n  WARNING: Low disk space! "
            f"(threshold: {config.storage.min_free_space_mb}MB)",
            err=True,
        )


@cli.command()
@click.pass_context
def daemon(ctx: click.Context) -> None:
    """Run as a daemon with scheduled captures."""
    config_path = ctx.obj.get("config_path")
    config = load_config(config_path)
    setup_logger(config.logging)

    click.echo("Starting Analemma daemon...")
    click.echo(f"  Capture time: {config.schedule.capture_time}")
    click.echo(f"  Timezone: {config.schedule.timezone}")
    click.echo(f"  Image format: {config.camera.image_type}")
    click.echo(f"  Storage path: {config.storage.base_path}")
    click.echo("\nPress Ctrl+C to stop.\n")

    system = AnalemmaSystem(config)

    try:
        system.run_daemon()
    except KeyboardInterrupt:
        click.echo("\nShutting down...")
    finally:
        system.stop()


@cli.command("config")
@click.option("--show", is_flag=True, help="Show current configuration")
@click.option("--create", is_flag=True, help="Create default configuration file")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("config/config.yaml"),
    help="Output path for configuration file",
)
@click.pass_context
def config_cmd(
    ctx: click.Context, show: bool, create: bool, output: Path
) -> None:
    """Manage configuration."""
    config_path = ctx.obj.get("config_path")

    if show:
        config = load_config(config_path)
        click.echo(yaml.dump(config.to_dict(), default_flow_style=False, allow_unicode=True))
        return

    if create:
        if output.exists():
            if not click.confirm(f"{output} already exists. Overwrite?"):
                return

        config = Config()
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, "w", encoding="utf-8") as f:
            yaml.dump(
                config.to_dict(), f, default_flow_style=False, allow_unicode=True
            )

        click.echo(f"Configuration file created: {output}")
        return

    # Default: show help
    ctx.invoke(config_cmd, show=True)


@cli.command("list-images")
@click.option(
    "--month",
    "-m",
    type=str,
    help="Filter by month (YYYY-MM format)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output as JSON",
)
@click.pass_context
def list_images(ctx: click.Context, month: Optional[str], as_json: bool) -> None:
    """List captured images."""
    config_path = ctx.obj.get("config_path")
    config = load_config(config_path)

    system = AnalemmaSystem(config)
    images = system.storage.list_images(year_month=month)

    if as_json:
        click.echo(json.dumps([str(p) for p in images], indent=2))
        return

    if not images:
        click.echo("No images found.")
        if month:
            click.echo(f"  (filtered by month: {month})")
        return

    click.echo(f"Found {len(images)} image(s):\n")
    for img in images:
        click.echo(f"  {img}")


if __name__ == "__main__":
    cli()
