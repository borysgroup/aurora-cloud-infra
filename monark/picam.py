"""
PiCam module for Raspberry Pi camera functionality in MonArk system.

This module provides camera capture, streaming, and configuration capabilities
for Raspberry Pi cameras using the picamera2 library.
"""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, Union, Any
import threading

import yaml

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    # Mock numpy for testing
    class np:
        uint8 = 'uint8'
        @staticmethod
        def zeros(shape, dtype=None):
            return [[0 for _ in range(shape[1]*shape[2])] for _ in range(shape[0])]

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    # Mock PIL for testing
    class Image:
        @staticmethod
        def fromarray(array):
            return MockImage()
    
    class MockImage:
        def save(self, filename):
            with open(filename, 'w') as f:
                f.write('mock image data')

try:
    from picamera2 import Picamera2
    from picamera2.encoders import H264Encoder
    from picamera2.outputs import FileOutput
    PICAMERA2_AVAILABLE = True
except ImportError:
    PICAMERA2_AVAILABLE = False
    # Mock classes for development/testing on non-Pi systems
    class Picamera2:
        def __init__(self):
            pass
        
        def configure(self, config):
            pass
        
        def create_still_configuration(self, main=None, lores=None):
            return {}
        
        def set_controls(self, controls):
            pass
        
        def start(self):
            pass
        
        def stop(self):
            pass
        
        def close(self):
            pass
        
        def capture_array(self):
            if NUMPY_AVAILABLE:
                return np.zeros((480, 640, 3), dtype=np.uint8)
            else:
                return [[0 for _ in range(640*3)] for _ in range(480)]
        
        def capture_file(self, filename):
            # Create a dummy image file
            if PIL_AVAILABLE and NUMPY_AVAILABLE:
                img = Image.fromarray(np.zeros((480, 640, 3), dtype=np.uint8))
                img.save(filename)
            else:
                with open(filename, 'w') as f:
                    f.write('mock camera capture')
        
        @property
        def camera_properties(self):
            return {'mock': 'properties'}


logger = logging.getLogger(__name__)


class PiCamConfig:
    """Configuration management for PiCam settings."""
    
    DEFAULT_CONFIG = {
        'resolution': (1920, 1080),
        'framerate': 30,
        'format': 'RGB888',
        'auto_exposure': True,
        'auto_white_balance': True,
        'brightness': 0.0,
        'contrast': 1.0,
        'saturation': 1.0,
        'sharpness': 1.0,
        'rotation': 0,
        'hflip': False,
        'vflip': False,
        'output_directory': './captures',
        'filename_prefix': 'capture',
        'timestamp_format': '%Y%m%d_%H%M%S'
    }
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration from file or defaults."""
        self.config = self.DEFAULT_CONFIG.copy()
        
        if config_path and Path(config_path).exists():
            self.load_from_file(config_path)
    
    def load_from_file(self, config_path: str) -> None:
        """Load configuration from YAML file."""
        try:
            with open(config_path, 'r') as f:
                file_config = yaml.safe_load(f)
                if file_config:
                    # Convert lists back to tuples for certain keys
                    for key, value in file_config.items():
                        if key == 'resolution' and isinstance(value, list):
                            file_config[key] = tuple(value)
                    self.config.update(file_config)
            logger.info(f"Configuration loaded from {config_path}")
        except Exception as e:
            logger.error(f"Failed to load configuration from {config_path}: {e}")
    
    def save_to_file(self, config_path: str) -> None:
        """Save current configuration to YAML file."""
        try:
            # Convert tuples to lists for YAML serialization
            yaml_config = {}
            for key, value in self.config.items():
                if isinstance(value, tuple):
                    yaml_config[key] = list(value)
                else:
                    yaml_config[key] = value
            
            with open(config_path, 'w') as f:
                yaml.dump(yaml_config, f, default_flow_style=False)
            logger.info(f"Configuration saved to {config_path}")
        except Exception as e:
            logger.error(f"Failed to save configuration to {config_path}: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Set configuration value."""
        self.config[key] = value
    
    def update(self, updates: Dict[str, Any]) -> None:
        """Update multiple configuration values."""
        self.config.update(updates)


class PiCam:
    """Raspberry Pi camera interface for MonArk monitoring system."""
    
    def __init__(self, config: Optional[PiCamConfig] = None):
        """Initialize PiCam with configuration."""
        self.config = config or PiCamConfig()
        self.camera: Optional[Picamera2] = None
        self.is_initialized = False
        self.is_streaming = False
        self._stream_thread: Optional[threading.Thread] = None
        self._stop_streaming = threading.Event()
        
        # Create output directory if it doesn't exist
        output_dir = Path(self.config.get('output_directory'))
        output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("PiCam initialized")
    
    def initialize(self) -> bool:
        """Initialize the camera hardware."""
        if not PICAMERA2_AVAILABLE:
            logger.warning("picamera2 not available - using mock camera for testing")
        
        try:
            self.camera = Picamera2()
            
            # Configure camera
            camera_config = self.camera.create_still_configuration(
                main={"size": self.config.get('resolution')},
                lores={"size": (640, 480), "format": "YUV420"}
            )
            self.camera.configure(camera_config)
            
            # Apply additional settings
            if PICAMERA2_AVAILABLE:
                controls = {}
                if not self.config.get('auto_exposure'):
                    controls['AeEnable'] = False
                if not self.config.get('auto_white_balance'):
                    controls['AwbEnable'] = False
                
                # Apply brightness, contrast, etc.
                brightness = self.config.get('brightness')
                if brightness != 0.0:
                    controls['Brightness'] = brightness
                
                contrast = self.config.get('contrast')
                if contrast != 1.0:
                    controls['Contrast'] = contrast
                
                if controls:
                    self.camera.set_controls(controls)
            
            self.camera.start()
            self.is_initialized = True
            logger.info("Camera initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize camera: {e}")
            self.is_initialized = False
            return False
    
    def cleanup(self) -> None:
        """Clean up camera resources."""
        if self.is_streaming:
            self.stop_streaming()
        
        if self.camera and self.is_initialized:
            try:
                self.camera.stop()
                self.camera.close()
                logger.info("Camera cleaned up successfully")
            except Exception as e:
                logger.error(f"Error during camera cleanup: {e}")
        
        self.is_initialized = False
        self.camera = None
    
    def capture_image(self, filename: Optional[str] = None) -> str:
        """Capture a single image and save to file."""
        if not self.is_initialized:
            raise RuntimeError("Camera not initialized")
        
        if filename is None:
            timestamp = datetime.now().strftime(self.config.get('timestamp_format'))
            prefix = self.config.get('filename_prefix')
            filename = f"{prefix}_{timestamp}.jpg"
        
        output_dir = Path(self.config.get('output_directory'))
        filepath = output_dir / filename
        
        try:
            self.camera.capture_file(str(filepath))
            logger.info(f"Image captured: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"Failed to capture image: {e}")
            raise
    
    def capture_array(self) -> any:
        """Capture image as numpy array."""
        if not self.is_initialized:
            raise RuntimeError("Camera not initialized")
        
        try:
            return self.camera.capture_array()
        except Exception as e:
            logger.error(f"Failed to capture array: {e}")
            raise
    
    def start_streaming(self, callback: Optional[callable] = None) -> None:
        """Start streaming frames in a separate thread."""
        if not self.is_initialized:
            raise RuntimeError("Camera not initialized")
        
        if self.is_streaming:
            logger.warning("Streaming already active")
            return
        
        self.is_streaming = True
        self._stop_streaming.clear()
        
        def stream_loop():
            """Main streaming loop."""
            logger.info("Started camera streaming")
            
            while not self._stop_streaming.is_set():
                try:
                    frame = self.camera.capture_array()
                    
                    if callback:
                        callback(frame)
                    
                    # Small delay to prevent excessive CPU usage
                    time.sleep(1.0 / self.config.get('framerate'))
                    
                except Exception as e:
                    logger.error(f"Error in streaming loop: {e}")
                    break
            
            logger.info("Camera streaming stopped")
        
        self._stream_thread = threading.Thread(target=stream_loop, daemon=True)
        self._stream_thread.start()
    
    def stop_streaming(self) -> None:
        """Stop the streaming thread."""
        if not self.is_streaming:
            return
        
        self._stop_streaming.set()
        
        if self._stream_thread and self._stream_thread.is_alive():
            self._stream_thread.join(timeout=5.0)
        
        self.is_streaming = False
        logger.info("Streaming stopped")
    
    def get_camera_info(self) -> Dict[str, Any]:
        """Get camera information and status."""
        info = {
            'initialized': self.is_initialized,
            'streaming': self.is_streaming,
            'picamera2_available': PICAMERA2_AVAILABLE,
            'configuration': self.config.config.copy()
        }
        
        if self.camera and self.is_initialized and PICAMERA2_AVAILABLE:
            try:
                # Add camera-specific information if available
                info['camera_properties'] = self.camera.camera_properties
            except Exception as e:
                logger.warning(f"Could not get camera properties: {e}")
        
        return info
    
    def update_config(self, updates: Dict[str, Any]) -> None:
        """Update camera configuration."""
        self.config.update(updates)
        logger.info(f"Configuration updated: {updates}")
        
        # Note: Some configuration changes may require camera restart
        if self.is_initialized:
            logger.info("Configuration changed - camera restart may be required for some settings")


def create_default_config(config_path: str) -> None:
    """Create a default configuration file."""
    config = PiCamConfig()
    config.save_to_file(config_path)
    print(f"Default configuration saved to {config_path}")


# Context manager for easy camera usage
class PiCamContext:
    """Context manager for PiCam operations."""
    
    def __init__(self, config: Optional[PiCamConfig] = None):
        self.picam = PiCam(config)
    
    def __enter__(self) -> PiCam:
        if not self.picam.initialize():
            raise RuntimeError("Failed to initialize camera")
        return self.picam
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.picam.cleanup()