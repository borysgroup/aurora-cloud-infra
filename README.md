# MonArk

MonArk is a monitoring system with Raspberry Pi camera support, designed for automated capture, streaming, and monitoring applications.

## Features

- **Raspberry Pi Camera Support**: Full integration with Raspberry Pi cameras using picamera2
- **Image Capture**: Single image capture with configurable settings
- **Video Streaming**: Real-time camera streaming with customizable frame rates
- **Timelapse Photography**: Automated timelapse capture with configurable intervals
- **Configuration Management**: YAML-based configuration with runtime updates
- **Command Line Interface**: Easy-to-use CLI for all camera operations
- **Cross-platform Development**: Mock camera support for development on non-Pi systems

## Installation

### On Raspberry Pi

```bash
# Clone the repository
git clone https://github.com/vertical-cloud-lab/MonArk.git
cd MonArk

# Install the package
pip install -e .
```

### For Development (Non-Pi Systems)

```bash
# Clone the repository
git clone https://github.com/vertical-cloud-lab/MonArk.git
cd MonArk

# Install with development dependencies
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize Configuration

```bash
# Create a default configuration file
monark init-config config.yaml
```

### 2. Capture an Image

```bash
# Capture with default settings
monark capture

# Capture with custom resolution
monark --config config.yaml capture --resolution 1920x1080 --output my_photo.jpg
```

### 3. Start Streaming

```bash
# Stream for 30 seconds at 30 fps
monark stream --duration 30 --framerate 30
```

### 4. Create a Timelapse

```bash
# Capture 60 images with 5-second intervals
monark timelapse --count 60 --interval 5 --prefix timelapse
```

## Configuration

The configuration file (`config.yaml`) allows you to customize camera settings:

```yaml
# Camera resolution (width, height)
resolution: [1920, 1080]

# Frame rate for streaming
framerate: 30

# Image format
format: RGB888

# Auto settings
auto_exposure: true
auto_white_balance: true

# Manual adjustments
brightness: 0.0      # -1.0 to 1.0
contrast: 1.0        # 0.0 to 2.0
saturation: 1.0      # 0.0 to 2.0
sharpness: 1.0       # 0.0 to 2.0

# Image orientation
rotation: 0          # 0, 90, 180, 270
hflip: false         # Horizontal flip
vflip: false         # Vertical flip

# Output settings
output_directory: ./captures
filename_prefix: capture
timestamp_format: '%Y%m%d_%H%M%S'
```

## CLI Commands

### Basic Commands

- `monark capture` - Capture a single image
- `monark stream` - Start camera streaming
- `monark info` - Display camera information
- `monark timelapse` - Create timelapse sequences

### Configuration Commands

- `monark init-config <file>` - Create default configuration
- `monark config-show` - Display current configuration
- `monark config-set --key <key> --value <value>` - Update configuration

### Examples

```bash
# Capture with custom settings
monark --config my_config.yaml capture --resolution 2592x1944

# Stream with verbose logging
monark --verbose stream --duration 60 --framerate 15

# Create timelapse with custom prefix
monark timelapse --count 100 --interval 10 --prefix sunset

# Update configuration
monark --config config.yaml config-set --key brightness --value 0.2 --type float
```

## Python API

You can also use MonArk programmatically:

```python
from monark.picam import PiCam, PiCamConfig, PiCamContext

# Basic usage with context manager
with PiCamContext() as camera:
    # Capture an image
    filepath = camera.capture_image()
    print(f"Image saved: {filepath}")
    
    # Start streaming
    def frame_handler(frame):
        print(f"Frame received: {frame.shape}")
    
    camera.start_streaming(callback=frame_handler)
    time.sleep(10)
    camera.stop_streaming()

# Advanced usage with custom configuration
config = PiCamConfig()
config.set('resolution', (2592, 1944))
config.set('framerate', 15)

camera = PiCam(config)
camera.initialize()

try:
    # Capture multiple images
    for i in range(5):
        filepath = camera.capture_image(f"image_{i:03d}.jpg")
        print(f"Captured: {filepath}")
        time.sleep(2)
finally:
    camera.cleanup()
```

## Requirements

### Raspberry Pi
- Raspberry Pi with camera module
- Python 3.8+
- picamera2 library
- RPi OS Bullseye or later

### Development
- Python 3.8+
- NumPy
- Pillow
- PyYAML
- Click

## Development

### Setting up Development Environment

```bash
# Clone and install in development mode
git clone https://github.com/vertical-cloud-lab/MonArk.git
cd MonArk
pip install -e ".[dev]"

# Run tests
pytest

# Code formatting
black monark/
flake8 monark/

# Type checking
mypy monark/
```

### Testing

The project includes comprehensive tests and mock camera support for development on non-Pi systems:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=monark

# Run specific test files
pytest tests/test_picam.py
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Support

For issues and questions:
- Create an issue on GitHub
- Contact: Vertical Cloud Lab @ BYU