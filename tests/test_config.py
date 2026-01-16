"""Tests for configuration module."""

import tempfile
from pathlib import Path

import pytest
import yaml

from analemma.config import (
    CameraConfig,
    Config,
    LoggingConfig,
    ScheduleConfig,
    StorageConfig,
    load_config,
    save_config,
)


class TestCameraConfig:
    """Tests for CameraConfig."""

    def test_default_values(self):
        """Test default camera configuration."""
        config = CameraConfig()
        assert config.exposure_us == 1000
        assert config.gain == 0
        assert config.image_type == "fits"

    def test_invalid_exposure(self):
        """Test that invalid exposure raises error."""
        with pytest.raises(ValueError, match="exposure_us must be positive"):
            CameraConfig(exposure_us=0)

    def test_invalid_gain(self):
        """Test that invalid gain raises error."""
        with pytest.raises(ValueError, match="gain must be between"):
            CameraConfig(gain=500)

    def test_invalid_image_type(self):
        """Test that invalid image type raises error."""
        with pytest.raises(ValueError, match="image_type must be"):
            CameraConfig(image_type="jpeg")


class TestScheduleConfig:
    """Tests for ScheduleConfig."""

    def test_default_values(self):
        """Test default schedule configuration."""
        config = ScheduleConfig()
        assert config.capture_time == "12:00"
        assert config.timezone == "Asia/Tokyo"

    def test_valid_capture_times(self):
        """Test various valid capture times."""
        for time in ["00:00", "12:30", "23:59"]:
            config = ScheduleConfig(capture_time=time)
            assert config.capture_time == time

    def test_invalid_capture_time_format(self):
        """Test that invalid time format raises error."""
        with pytest.raises(ValueError, match="HH:MM format"):
            ScheduleConfig(capture_time="12")

    def test_invalid_capture_time_values(self):
        """Test that invalid time values raise error."""
        with pytest.raises(ValueError, match="HH:MM format"):
            ScheduleConfig(capture_time="25:00")


class TestStorageConfig:
    """Tests for StorageConfig."""

    def test_default_values(self):
        """Test default storage configuration."""
        config = StorageConfig()
        assert config.base_path == Path("/home/pi/analemma/images")
        assert config.monthly_subfolders is True
        assert config.min_free_space_mb == 1024

    def test_string_path_conversion(self):
        """Test that string paths are converted to Path objects."""
        config = StorageConfig(base_path="/tmp/test")
        assert isinstance(config.base_path, Path)
        assert config.base_path == Path("/tmp/test")


class TestLoggingConfig:
    """Tests for LoggingConfig."""

    def test_default_values(self):
        """Test default logging configuration."""
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.max_size_mb == 10
        assert config.backup_count == 5

    def test_level_case_insensitive(self):
        """Test that log level is case insensitive."""
        config = LoggingConfig(level="debug")
        assert config.level == "DEBUG"

    def test_invalid_level(self):
        """Test that invalid log level raises error."""
        with pytest.raises(ValueError, match="level must be one of"):
            LoggingConfig(level="TRACE")


class TestConfig:
    """Tests for main Config class."""

    def test_from_dict(self):
        """Test creating Config from dictionary."""
        data = {
            "camera": {"exposure_us": 2000, "gain": 50},
            "schedule": {"capture_time": "11:30"},
            "storage": {"monthly_subfolders": False},
            "logging": {"level": "DEBUG"},
        }
        config = Config.from_dict(data)
        assert config.camera.exposure_us == 2000
        assert config.camera.gain == 50
        assert config.schedule.capture_time == "11:30"
        assert config.storage.monthly_subfolders is False
        assert config.logging.level == "DEBUG"

    def test_to_dict(self):
        """Test converting Config to dictionary."""
        config = Config()
        data = config.to_dict()
        assert "camera" in data
        assert "schedule" in data
        assert "storage" in data
        assert "logging" in data
        assert data["camera"]["exposure_us"] == 1000


class TestLoadSaveConfig:
    """Tests for load_config and save_config functions."""

    def test_load_nonexistent_file(self):
        """Test loading when config file doesn't exist."""
        config = load_config(Path("/nonexistent/path.yaml"))
        # Should return default config
        assert config.camera.exposure_us == 1000

    def test_save_and_load_config(self):
        """Test saving and loading configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"

            # Create custom config
            config = Config()
            config.camera.exposure_us = 5000
            config.schedule.capture_time = "10:00"

            # Save
            save_config(config, config_path)
            assert config_path.exists()

            # Load
            loaded = load_config(config_path)
            assert loaded.camera.exposure_us == 5000
            assert loaded.schedule.capture_time == "10:00"

    def test_load_empty_file(self):
        """Test loading empty config file."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(b"")
            config_path = Path(f.name)

        try:
            config = load_config(config_path)
            # Should return default config
            assert config.camera.exposure_us == 1000
        finally:
            config_path.unlink()
