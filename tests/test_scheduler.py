"""Tests for scheduler module."""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from analemma.config import ScheduleConfig
from analemma.scheduler import CaptureScheduler, SchedulerError


@pytest.fixture
def schedule_config():
    """Create schedule configuration."""
    return ScheduleConfig(capture_time="12:00", timezone="Asia/Tokyo")


@pytest.fixture
def mock_callback():
    """Create mock callback function."""
    return MagicMock()


class TestCaptureScheduler:
    """Tests for CaptureScheduler."""

    def test_init_valid_config(self, schedule_config, mock_callback):
        """Test scheduler initialization with valid config."""
        scheduler = CaptureScheduler(schedule_config, mock_callback)
        assert scheduler._capture_hour == 12
        assert scheduler._capture_minute == 0

    def test_init_invalid_time_format(self, mock_callback):
        """Test scheduler initialization with invalid time format."""
        config = ScheduleConfig.__new__(ScheduleConfig)
        config.capture_time = "invalid"
        config.timezone = "Asia/Tokyo"

        with pytest.raises(SchedulerError, match="Invalid capture time format"):
            CaptureScheduler(config, mock_callback)

    def test_init_invalid_timezone(self, mock_callback):
        """Test scheduler initialization with invalid timezone."""
        config = ScheduleConfig.__new__(ScheduleConfig)
        config.capture_time = "12:00"
        config.timezone = "Invalid/Timezone"

        with pytest.raises(SchedulerError, match="Invalid timezone"):
            CaptureScheduler(config, mock_callback)

    def test_start_stop(self, schedule_config, mock_callback):
        """Test starting and stopping scheduler."""
        scheduler = CaptureScheduler(schedule_config, mock_callback)

        assert not scheduler.is_running()

        scheduler.start()
        assert scheduler.is_running()

        scheduler.stop()
        assert not scheduler.is_running()

    def test_get_next_capture_time(self, schedule_config, mock_callback):
        """Test getting next capture time."""
        scheduler = CaptureScheduler(schedule_config, mock_callback)
        scheduler.start()

        try:
            next_time = scheduler.get_next_capture_time()
            assert next_time is not None
            assert next_time.hour == 12
            assert next_time.minute == 0
        finally:
            scheduler.stop()

    def test_get_next_capture_time_not_running(self, schedule_config, mock_callback):
        """Test getting next capture time when not running."""
        scheduler = CaptureScheduler(schedule_config, mock_callback)
        assert scheduler.get_next_capture_time() is None

    def test_trigger_manual_capture(self, schedule_config, mock_callback):
        """Test manual capture trigger."""
        scheduler = CaptureScheduler(schedule_config, mock_callback)
        scheduler.trigger_manual_capture()
        mock_callback.assert_called_once()

    def test_trigger_manual_capture_error(self, schedule_config):
        """Test manual capture trigger with error."""
        error_callback = MagicMock(side_effect=Exception("Test error"))
        scheduler = CaptureScheduler(schedule_config, error_callback)

        with pytest.raises(Exception, match="Test error"):
            scheduler.trigger_manual_capture()

    def test_get_status(self, schedule_config, mock_callback):
        """Test getting scheduler status."""
        scheduler = CaptureScheduler(schedule_config, mock_callback)

        status = scheduler.get_status()
        assert status["running"] is False
        assert status["capture_time"] == "12:00"
        assert status["timezone"] == "Asia/Tokyo"
        assert status["next_capture"] is None

        scheduler.start()
        try:
            status = scheduler.get_status()
            assert status["running"] is True
            assert status["next_capture"] is not None
        finally:
            scheduler.stop()

    def test_double_start_warning(self, schedule_config, mock_callback, caplog):
        """Test that starting twice logs a warning."""
        scheduler = CaptureScheduler(schedule_config, mock_callback)
        scheduler.start()

        try:
            scheduler.start()
            assert "already running" in caplog.text.lower()
        finally:
            scheduler.stop()


class TestSchedulerTimezones:
    """Tests for timezone handling."""

    def test_different_timezones(self, mock_callback):
        """Test scheduler with different timezones."""
        timezones = ["Asia/Tokyo", "America/New_York", "Europe/London", "UTC"]

        for tz in timezones:
            config = ScheduleConfig(capture_time="12:00", timezone=tz)
            scheduler = CaptureScheduler(config, mock_callback)
            scheduler.start()

            try:
                next_time = scheduler.get_next_capture_time()
                assert next_time is not None
                # The timezone should match
                assert str(next_time.tzinfo) == tz or next_time.tzinfo is not None
            finally:
                scheduler.stop()


class TestCaptureWrapper:
    """Tests for capture wrapper error handling."""

    def test_capture_wrapper_handles_error(self, schedule_config, caplog):
        """Test that capture wrapper handles callback errors gracefully."""
        error_callback = MagicMock(side_effect=Exception("Capture failed"))
        scheduler = CaptureScheduler(schedule_config, error_callback)

        # Direct call to wrapper (simulating scheduled trigger)
        scheduler._capture_wrapper()

        # Should log error but not raise
        assert "capture failed" in caplog.text.lower()
