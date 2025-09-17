"""
Tests for PiCam functionality.
"""

import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
import numpy as np

from monark.picam import PiCam, PiCamConfig, PiCamContext


class TestPiCamConfig:
    """Test PiCamConfig class."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = PiCamConfig()
        
        assert config.get('resolution') == (1920, 1080)
        assert config.get('framerate') == 30
        assert config.get('format') == 'RGB888'
        assert config.get('auto_exposure') is True
        assert config.get('brightness') == 0.0
        assert config.get('output_directory') == './captures'
    
    def test_config_get_set(self):
        """Test getting and setting configuration values."""
        config = PiCamConfig()
        
        # Test setting and getting values
        config.set('resolution', (1280, 720))
        assert config.get('resolution') == (1280, 720)
        
        config.set('framerate', 60)
        assert config.get('framerate') == 60
        
        # Test default values
        assert config.get('nonexistent_key', 'default') == 'default'
    
    def test_config_update(self):
        """Test updating multiple configuration values."""
        config = PiCamConfig()
        
        updates = {
            'resolution': (640, 480),
            'framerate': 15,
            'brightness': 0.5
        }
        
        config.update(updates)
        
        assert config.get('resolution') == (640, 480)
        assert config.get('framerate') == 15
        assert config.get('brightness') == 0.5
    
    def test_config_file_operations(self):
        """Test loading and saving configuration files."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_path = f.name
        
        try:
            # Create and save configuration
            config1 = PiCamConfig()
            config1.set('resolution', (800, 600))
            config1.set('framerate', 25)
            config1.save_to_file(config_path)
            
            # Load configuration from file
            config2 = PiCamConfig(config_path)
            assert config2.get('resolution') == (800, 600)
            assert config2.get('framerate') == 25
            
        finally:
            Path(config_path).unlink(missing_ok=True)


class TestPiCam:
    """Test PiCam class."""
    
    def test_picam_initialization(self):
        """Test PiCam initialization."""
        config = PiCamConfig()
        picam = PiCam(config)
        
        assert picam.config == config
        assert not picam.is_initialized
        assert not picam.is_streaming
        assert picam.camera is None
    
    def test_picam_initialize_success(self):
        """Test successful camera initialization."""
        config = PiCamConfig()
        picam = PiCam(config)
        
        # Mock successful initialization
        with patch('monark.picam.Picamera2') as mock_camera_class:
            mock_camera = MagicMock()
            mock_camera_class.return_value = mock_camera
            
            result = picam.initialize()
            
            assert result is True
            assert picam.is_initialized is True
            assert picam.camera == mock_camera
            mock_camera.configure.assert_called_once()
            mock_camera.start.assert_called_once()
    
    def test_picam_initialize_failure(self):
        """Test camera initialization failure."""
        config = PiCamConfig()
        picam = PiCam(config)
        
        # Mock initialization failure
        with patch('monark.picam.Picamera2') as mock_camera_class:
            mock_camera_class.side_effect = Exception("Camera not found")
            
            result = picam.initialize()
            
            assert result is False
            assert picam.is_initialized is False
    
    def test_picam_cleanup(self):
        """Test camera cleanup."""
        config = PiCamConfig()
        picam = PiCam(config)
        
        with patch('monark.picam.Picamera2') as mock_camera_class:
            mock_camera = MagicMock()
            mock_camera_class.return_value = mock_camera
            
            # Initialize and then cleanup
            picam.initialize()
            picam.cleanup()
            
            assert not picam.is_initialized
            assert picam.camera is None
            mock_camera.stop.assert_called_once()
            mock_camera.close.assert_called_once()
    
    def test_capture_image_not_initialized(self):
        """Test capturing image when camera not initialized."""
        config = PiCamConfig()
        picam = PiCam(config)
        
        with pytest.raises(RuntimeError, match="Camera not initialized"):
            picam.capture_image()
    
    def test_capture_image_success(self):
        """Test successful image capture."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = PiCamConfig()
            config.set('output_directory', temp_dir)
            picam = PiCam(config)
            
            with patch('monark.picam.Picamera2') as mock_camera_class:
                mock_camera = MagicMock()
                mock_camera_class.return_value = mock_camera
                
                picam.initialize()
                filepath = picam.capture_image("test.jpg")
                
                expected_path = Path(temp_dir) / "test.jpg"
                assert filepath == str(expected_path)
                mock_camera.capture_file.assert_called_once_with(str(expected_path))
    
    def test_capture_array_success(self):
        """Test successful array capture."""
        config = PiCamConfig()
        picam = PiCam(config)
        
        test_array = np.zeros((480, 640, 3), dtype=np.uint8)
        
        with patch('monark.picam.Picamera2') as mock_camera_class:
            mock_camera = MagicMock()
            mock_camera.capture_array.return_value = test_array
            mock_camera_class.return_value = mock_camera
            
            picam.initialize()
            result = picam.capture_array()
            
            np.testing.assert_array_equal(result, test_array)
            mock_camera.capture_array.assert_called_once()
    
    def test_streaming_not_initialized(self):
        """Test streaming when camera not initialized."""
        config = PiCamConfig()
        picam = PiCam(config)
        
        with pytest.raises(RuntimeError, match="Camera not initialized"):
            picam.start_streaming()
    
    def test_streaming_lifecycle(self):
        """Test streaming start and stop."""
        config = PiCamConfig()
        config.set('framerate', 10)  # Lower framerate for testing
        picam = PiCam(config)
        
        with patch('monark.picam.Picamera2') as mock_camera_class:
            mock_camera = MagicMock()
            mock_camera.capture_array.return_value = np.zeros((480, 640, 3), dtype=np.uint8)
            mock_camera_class.return_value = mock_camera
            
            picam.initialize()
            
            # Test starting streaming
            callback_calls = []
            def test_callback(frame):
                callback_calls.append(frame)
            
            picam.start_streaming(callback=test_callback)
            assert picam.is_streaming is True
            
            # Let it run briefly
            time.sleep(0.3)
            
            # Test stopping streaming
            picam.stop_streaming()
            assert picam.is_streaming is False
            
            # Verify callback was called
            assert len(callback_calls) > 0
    
    def test_get_camera_info(self):
        """Test getting camera information."""
        config = PiCamConfig()
        picam = PiCam(config)
        
        # Test before initialization
        info = picam.get_camera_info()
        assert info['initialized'] is False
        assert info['streaming'] is False
        assert 'configuration' in info
        
        # Test after initialization
        with patch('monark.picam.Picamera2') as mock_camera_class:
            mock_camera = MagicMock()
            mock_camera.camera_properties = {'test': 'value'}
            mock_camera_class.return_value = mock_camera
            
            picam.initialize()
            info = picam.get_camera_info()
            
            assert info['initialized'] is True
            assert 'configuration' in info
    
    def test_update_config(self):
        """Test updating configuration."""
        config = PiCamConfig()
        picam = PiCam(config)
        
        updates = {'resolution': (1280, 720), 'framerate': 25}
        picam.update_config(updates)
        
        assert picam.config.get('resolution') == (1280, 720)
        assert picam.config.get('framerate') == 25


class TestPiCamContext:
    """Test PiCamContext context manager."""
    
    def test_context_manager_success(self):
        """Test successful context manager usage."""
        config = PiCamConfig()
        
        with patch('monark.picam.Picamera2') as mock_camera_class:
            mock_camera = MagicMock()
            mock_camera_class.return_value = mock_camera
            
            with PiCamContext(config) as picam:
                assert isinstance(picam, PiCam)
                assert picam.is_initialized is True
            
            # Verify cleanup was called
            mock_camera.stop.assert_called_once()
            mock_camera.close.assert_called_once()
    
    def test_context_manager_initialization_failure(self):
        """Test context manager with initialization failure."""
        config = PiCamConfig()
        
        with patch('monark.picam.Picamera2') as mock_camera_class:
            mock_camera_class.side_effect = Exception("Camera not found")
            
            with pytest.raises(RuntimeError, match="Failed to initialize camera"):
                with PiCamContext(config) as picam:
                    pass


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_create_default_config(self):
        """Test creating default configuration file."""
        from monark.picam import create_default_config
        
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as f:
            config_path = f.name
        
        try:
            create_default_config(config_path)
            
            # Verify file was created and contains expected content
            assert Path(config_path).exists()
            
            # Load and verify content
            config = PiCamConfig(config_path)
            assert config.get('resolution') == (1920, 1080)
            assert config.get('framerate') == 30
            
        finally:
            Path(config_path).unlink(missing_ok=True)