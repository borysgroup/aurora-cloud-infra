#!/usr/bin/env python3
"""
Basic PiCam usage example for MonArk system.

This example demonstrates how to use the MonArk PiCam module to:
1. Initialize the camera
2. Capture a single image
3. Stream video frames
4. Create a timelapse sequence
"""

import time
import sys
from pathlib import Path

# Add the parent directory to the path so we can import monark
sys.path.insert(0, str(Path(__file__).parent.parent))

from monark.picam import PiCam, PiCamConfig, PiCamContext


def basic_capture_example():
    """Example: Capture a single image using context manager."""
    print("=== Basic Image Capture Example ===")
    
    # Create configuration
    config = PiCamConfig()
    config.set('resolution', (1280, 720))  # Lower resolution for example
    config.set('output_directory', './example_captures')
    
    try:
        # Use context manager for automatic cleanup
        with PiCamContext(config) as camera:
            print("Camera initialized successfully!")
            
            # Capture an image
            filepath = camera.capture_image("example_photo.jpg")
            print(f"Image captured: {filepath}")
            
    except Exception as e:
        print(f"Error: {e}")


def streaming_example():
    """Example: Stream video frames with callback."""
    print("\n=== Video Streaming Example ===")
    
    config = PiCamConfig()
    config.set('framerate', 10)  # Lower framerate for example
    
    frame_count = 0
    
    def frame_handler(frame):
        """Handle each frame received from the camera."""
        nonlocal frame_count
        frame_count += 1
        if frame_count % 10 == 0:
            print(f"Received {frame_count} frames...")
    
    try:
        with PiCamContext(config) as camera:
            print("Starting video stream for 5 seconds...")
            
            # Start streaming
            camera.start_streaming(callback=frame_handler)
            
            # Let it run for 5 seconds
            time.sleep(5)
            
            # Stop streaming
            camera.stop_streaming()
            print(f"Streaming completed. Total frames: {frame_count}")
            
    except Exception as e:
        print(f"Error: {e}")


def timelapse_example():
    """Example: Create a timelapse sequence."""
    print("\n=== Timelapse Example ===")
    
    config = PiCamConfig()
    config.set('filename_prefix', 'timelapse')
    config.set('output_directory', './example_captures')
    
    try:
        with PiCamContext(config) as camera:
            print("Creating timelapse: 5 images, 1 second apart...")
            
            captured_files = []
            for i in range(5):
                filepath = camera.capture_image(f"timelapse_{i:03d}.jpg")
                captured_files.append(filepath)
                print(f"Captured {i+1}/5: {filepath}")
                
                if i < 4:  # Don't wait after the last image
                    time.sleep(1)
            
            print("Timelapse completed!")
            print("Captured files:")
            for filepath in captured_files:
                print(f"  {filepath}")
                
    except Exception as e:
        print(f"Error: {e}")


def configuration_example():
    """Example: Working with configuration."""
    print("\n=== Configuration Example ===")
    
    # Create configuration with custom settings
    config = PiCamConfig()
    
    # Update settings
    config.update({
        'resolution': (640, 480),
        'framerate': 15,
        'brightness': 0.2,
        'contrast': 1.2,
        'output_directory': './example_captures'
    })
    
    print("Custom configuration:")
    for key, value in config.config.items():
        print(f"  {key}: {value}")
    
    # Save configuration to file
    config.save_to_file('example_config.yaml')
    print("\nConfiguration saved to example_config.yaml")
    
    # Load configuration from file
    new_config = PiCamConfig('example_config.yaml')
    print(f"Loaded resolution: {new_config.get('resolution')}")
    print(f"Loaded framerate: {new_config.get('framerate')}")


def camera_info_example():
    """Example: Get camera information."""
    print("\n=== Camera Information Example ===")
    
    config = PiCamConfig()
    
    try:
        with PiCamContext(config) as camera:
            info = camera.get_camera_info()
            
            print("Camera Status:")
            print(f"  Initialized: {info['initialized']}")
            print(f"  Streaming: {info['streaming']}")
            print(f"  PiCamera2 Available: {info['picamera2_available']}")
            
            if 'camera_properties' in info:
                print("Camera Properties:")
                for key, value in info['camera_properties'].items():
                    print(f"  {key}: {value}")
                    
    except Exception as e:
        print(f"Error: {e}")


def main():
    """Run all examples."""
    print("MonArk PiCam Examples")
    print("=" * 50)
    
    # Run examples
    basic_capture_example()
    streaming_example()
    timelapse_example()
    configuration_example()
    camera_info_example()
    
    print("\n" + "=" * 50)
    print("All examples completed!")
    print("\nNote: If running on a non-Raspberry Pi system,")
    print("mock camera functionality is used for demonstration.")


if __name__ == '__main__':
    main()