"""
Command Line Interface for MonArk PiCam functionality.
"""

import logging
import sys
import time
from pathlib import Path
from typing import Optional

import click
import yaml

from .picam import PiCam, PiCamConfig, PiCamContext, create_default_config


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@click.group()
@click.option('--config', '-c', type=click.Path(exists=True), help='Configuration file path')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.pass_context
def main(ctx, config: Optional[str], verbose: bool):
    """MonArk - Raspberry Pi Camera Monitoring System."""
    if verbose:
        logging.getLogger('monark').setLevel(logging.DEBUG)
    
    # Create context object to pass configuration
    ctx.ensure_object(dict)
    ctx.obj['config_path'] = config
    
    if config:
        click.echo(f"Using configuration: {config}")


@main.command()
@click.option('--output', '-o', type=click.Path(), help='Output file path')
@click.option('--resolution', type=str, help='Resolution (e.g., "1920x1080")')
@click.pass_context
def capture(ctx, output: Optional[str], resolution: Optional[str]):
    """Capture a single image from the camera."""
    config_path = ctx.obj.get('config_path')
    
    try:
        # Load configuration
        config = PiCamConfig(config_path)
        
        # Update resolution if provided
        if resolution:
            try:
                width, height = map(int, resolution.split('x'))
                config.set('resolution', (width, height))
            except ValueError:
                click.echo("Error: Invalid resolution format. Use 'WIDTHxHEIGHT' (e.g., '1920x1080')")
                sys.exit(1)
        
        # Capture image
        with PiCamContext(config) as picam:
            if output:
                filepath = picam.capture_image(output)
            else:
                filepath = picam.capture_image()
            
            click.echo(f"Image captured: {filepath}")
    
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option('--duration', '-d', type=int, default=10, help='Streaming duration in seconds')
@click.option('--framerate', '-f', type=int, help='Frame rate (fps)')
@click.pass_context
def stream(ctx, duration: int, framerate: Optional[int]):
    """Start camera streaming for a specified duration."""
    config_path = ctx.obj.get('config_path')
    
    try:
        # Load configuration
        config = PiCamConfig(config_path)
        
        # Update framerate if provided
        if framerate:
            config.set('framerate', framerate)
        
        frame_count = 0
        
        def frame_callback(frame):
            nonlocal frame_count
            frame_count += 1
            if frame_count % config.get('framerate') == 0:
                click.echo(f"Streaming... {frame_count // config.get('framerate')}s")
        
        # Start streaming
        with PiCamContext(config) as picam:
            click.echo(f"Starting stream for {duration} seconds at {config.get('framerate')} fps...")
            
            picam.start_streaming(callback=frame_callback)
            time.sleep(duration)
            picam.stop_streaming()
            
            click.echo(f"Streaming completed. Total frames: {frame_count}")
    
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.pass_context
def info(ctx):
    """Display camera information and status."""
    config_path = ctx.obj.get('config_path')
    
    try:
        config = PiCamConfig(config_path)
        
        with PiCamContext(config) as picam:
            info_data = picam.get_camera_info()
            
            click.echo("Camera Information:")
            click.echo("=" * 50)
            
            # Display status
            click.echo(f"Initialized: {info_data['initialized']}")
            click.echo(f"Streaming: {info_data['streaming']}")
            click.echo(f"PiCamera2 Available: {info_data['picamera2_available']}")
            
            # Display configuration
            click.echo("\nConfiguration:")
            click.echo("-" * 30)
            config_data = info_data['configuration']
            for key, value in config_data.items():
                click.echo(f"{key}: {value}")
            
            # Display camera properties if available
            if 'camera_properties' in info_data:
                click.echo("\nCamera Properties:")
                click.echo("-" * 30)
                props = info_data['camera_properties']
                for key, value in props.items():
                    click.echo(f"{key}: {value}")
    
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument('config_file', type=click.Path())
def init_config(config_file: str):
    """Create a default configuration file."""
    try:
        create_default_config(config_file)
        click.echo(f"Default configuration created: {config_file}")
    except Exception as e:
        click.echo(f"Error creating configuration: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option('--key', '-k', required=True, help='Configuration key to set')
@click.option('--value', '-v', required=True, help='Configuration value')
@click.option('--type', '-t', type=click.Choice(['str', 'int', 'float', 'bool']), 
              default='str', help='Value type')
@click.pass_context
def config_set(ctx, key: str, value: str, type: str):
    """Set a configuration value."""
    config_path = ctx.obj.get('config_path')
    
    if not config_path:
        click.echo("Error: No configuration file specified. Use --config or create one with init-config.")
        sys.exit(1)
    
    try:
        # Convert value to appropriate type
        if type == 'int':
            converted_value = int(value)
        elif type == 'float':
            converted_value = float(value)
        elif type == 'bool':
            converted_value = value.lower() in ('true', '1', 'yes', 'on')
        else:
            converted_value = value
        
        # Load, update, and save configuration
        config = PiCamConfig(config_path)
        config.set(key, converted_value)
        config.save_to_file(config_path)
        
        click.echo(f"Configuration updated: {key} = {converted_value}")
    
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.pass_context
def config_show(ctx):
    """Show current configuration."""
    config_path = ctx.obj.get('config_path')
    
    try:
        config = PiCamConfig(config_path)
        
        click.echo("Current Configuration:")
        click.echo("=" * 50)
        
        for key, value in config.config.items():
            click.echo(f"{key}: {value}")
    
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option('--count', '-n', type=int, default=1, help='Number of images to capture')
@click.option('--interval', '-i', type=float, default=1.0, help='Interval between captures (seconds)')
@click.option('--prefix', '-p', type=str, help='Filename prefix')
@click.pass_context
def timelapse(ctx, count: int, interval: float, prefix: Optional[str]):
    """Capture multiple images at regular intervals."""
    config_path = ctx.obj.get('config_path')
    
    try:
        config = PiCamConfig(config_path)
        
        if prefix:
            config.set('filename_prefix', prefix)
        
        captured_files = []
        
        with PiCamContext(config) as picam:
            click.echo(f"Starting timelapse: {count} images, {interval}s interval")
            
            for i in range(count):
                filepath = picam.capture_image()
                captured_files.append(filepath)
                click.echo(f"Captured {i+1}/{count}: {filepath}")
                
                if i < count - 1:  # Don't wait after the last image
                    time.sleep(interval)
            
            click.echo(f"\nTimelapse completed. Captured {len(captured_files)} images:")
            for filepath in captured_files:
                click.echo(f"  {filepath}")
    
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == '__main__':
    main()