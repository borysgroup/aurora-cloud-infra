"""
Tests for CLI functionality.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from monark.cli import main
from monark.picam import PiCamConfig


class TestCLI:
    """Test CLI commands."""
    
    def test_main_help(self):
        """Test main command help."""
        runner = CliRunner()
        result = runner.invoke(main, ['--help'])
        
        assert result.exit_code == 0
        assert 'MonArk' in result.output
        assert 'capture' in result.output
        assert 'stream' in result.output
    
    def test_init_config(self):
        """Test init-config command."""
        runner = CliRunner()
        
        with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as f:
            config_path = f.name
        
        try:
            result = runner.invoke(main, ['init-config', config_path])
            
            assert result.exit_code == 0
            assert 'Default configuration created' in result.output
            assert Path(config_path).exists()
            
            # Verify config content
            config = PiCamConfig(config_path)
            assert config.get('resolution') == (1920, 1080)
            
        finally:
            Path(config_path).unlink(missing_ok=True)
    
    def test_config_show(self):
        """Test config-show command."""
        runner = CliRunner()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_path = f.name
        
        try:
            # Create a config file
            config = PiCamConfig()
            config.save_to_file(config_path)
            
            result = runner.invoke(main, ['--config', config_path, 'config-show'])
            
            assert result.exit_code == 0
            assert 'Current Configuration' in result.output
            assert 'resolution:' in result.output
            
        finally:
            Path(config_path).unlink(missing_ok=True)
    
    def test_config_set(self):
        """Test config-set command."""
        runner = CliRunner()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            config_path = f.name
        
        try:
            # Create initial config
            config = PiCamConfig()
            config.save_to_file(config_path)
            
            # Update configuration
            result = runner.invoke(main, [
                '--config', config_path,
                'config-set',
                '--key', 'framerate',
                '--value', '60',
                '--type', 'int'
            ])
            
            assert result.exit_code == 0
            assert 'Configuration updated' in result.output
            
            # Verify the update
            updated_config = PiCamConfig(config_path)
            assert updated_config.get('framerate') == 60
            
        finally:
            Path(config_path).unlink(missing_ok=True)
    
    @patch('monark.picam.Picamera2')
    def test_capture_command(self, mock_camera_class):
        """Test capture command."""
        mock_camera = MagicMock()
        mock_camera_class.return_value = mock_camera
        
        runner = CliRunner()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = runner.invoke(main, [
                'capture',
                '--resolution', '1280x720',
                '--output', f'{temp_dir}/test.jpg'
            ])
            
            assert result.exit_code == 0
            assert 'Image captured' in result.output
    
    @patch('monark.picam.Picamera2')
    def test_info_command(self, mock_camera_class):
        """Test info command."""
        mock_camera = MagicMock()
        mock_camera.camera_properties = {'test': 'value'}
        mock_camera_class.return_value = mock_camera
        
        runner = CliRunner()
        result = runner.invoke(main, ['info'])
        
        assert result.exit_code == 0
        assert 'Camera Information' in result.output
        assert 'Initialized:' in result.output
    
    @patch('monark.picam.Picamera2')
    def test_timelapse_command(self, mock_camera_class):
        """Test timelapse command."""
        mock_camera = MagicMock()
        mock_camera_class.return_value = mock_camera
        
        runner = CliRunner()
        result = runner.invoke(main, [
            'timelapse',
            '--count', '3',
            '--interval', '0.1',
            '--prefix', 'test'
        ])
        
        assert result.exit_code == 0
        assert 'Timelapse completed' in result.output
        assert 'Captured 3 images' in result.output
    
    def test_capture_invalid_resolution(self):
        """Test capture with invalid resolution format."""
        runner = CliRunner()
        result = runner.invoke(main, [
            'capture',
            '--resolution', 'invalid'
        ])
        
        assert result.exit_code == 1
        assert 'Invalid resolution format' in result.output
    
    def test_config_set_no_config_file(self):
        """Test config-set without specifying config file."""
        runner = CliRunner()
        result = runner.invoke(main, [
            'config-set',
            '--key', 'framerate',
            '--value', '30'
        ])
        
        assert result.exit_code == 1
        assert 'No configuration file specified' in result.output