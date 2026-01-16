"""Scheduler module for Analemma Capture System."""

from datetime import datetime
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from analemma.config import ScheduleConfig
from analemma.logger import get_logger

logger = get_logger(__name__)


class SchedulerError(Exception):
    """Exception raised for scheduler-related errors."""

    pass


class CaptureScheduler:
    """Capture schedule manager using APScheduler."""

    def __init__(
        self,
        config: ScheduleConfig,
        on_capture: Callable[[], None],
    ):
        """Initialize the scheduler.

        Args:
            config: Schedule configuration.
            on_capture: Callback function to execute on scheduled capture.
        """
        self.config = config
        self.on_capture = on_capture
        self._scheduler: Optional[BackgroundScheduler] = None
        self._job_id = "daily_capture"

        # Parse capture time
        try:
            parts = config.capture_time.split(":")
            self._capture_hour = int(parts[0])
            self._capture_minute = int(parts[1])
        except (ValueError, IndexError):
            raise SchedulerError(
                f"Invalid capture time format: {config.capture_time}. "
                "Expected HH:MM format."
            )

        # Validate timezone
        try:
            self._timezone = ZoneInfo(config.timezone)
        except KeyError:
            raise SchedulerError(f"Invalid timezone: {config.timezone}")

    def start(self) -> None:
        """Start the scheduler."""
        if self._scheduler is not None and self._scheduler.running:
            logger.warning("Scheduler already running")
            return

        self._scheduler = BackgroundScheduler(timezone=self._timezone)

        # Create cron trigger for daily capture
        trigger = CronTrigger(
            hour=self._capture_hour,
            minute=self._capture_minute,
            timezone=self._timezone,
        )

        # Add job
        self._scheduler.add_job(
            self._capture_wrapper,
            trigger=trigger,
            id=self._job_id,
            name="Daily Solar Capture",
            replace_existing=True,
        )

        self._scheduler.start()

        next_run = self.get_next_capture_time()
        logger.info(
            f"Scheduler started. Next capture at {next_run.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=True)
            self._scheduler = None
            logger.info("Scheduler stopped")

    def _capture_wrapper(self) -> None:
        """Wrapper for capture callback with error handling."""
        logger.info("Scheduled capture triggered")
        try:
            self.on_capture()
        except Exception as e:
            logger.error(f"Capture failed: {e}")

    def get_next_capture_time(self) -> Optional[datetime]:
        """Get the next scheduled capture time.

        Returns:
            Next capture datetime with timezone info, or None if scheduler not running.
        """
        if self._scheduler is None or not self._scheduler.running:
            return None

        job = self._scheduler.get_job(self._job_id)
        if job is None:
            return None

        return job.next_run_time

    def trigger_manual_capture(self) -> None:
        """Trigger an immediate manual capture.

        This bypasses the schedule and executes capture immediately.
        """
        logger.info("Manual capture triggered")
        try:
            self.on_capture()
        except Exception as e:
            logger.error(f"Manual capture failed: {e}")
            raise

    def is_running(self) -> bool:
        """Check if scheduler is running.

        Returns:
            True if scheduler is active.
        """
        return self._scheduler is not None and self._scheduler.running

    def get_status(self) -> dict:
        """Get scheduler status information.

        Returns:
            Dictionary with scheduler status.
        """
        next_capture = self.get_next_capture_time()

        return {
            "running": self.is_running(),
            "capture_time": self.config.capture_time,
            "timezone": self.config.timezone,
            "next_capture": next_capture.isoformat() if next_capture else None,
        }
