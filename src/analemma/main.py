"""Main module for Analemma Capture System.

This module integrates all components and provides the capture workflow.
"""

import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from analemma.camera import (
    CameraConnectionError,
    CameraController,
    CameraError,
    CaptureError,
)
from analemma.config import Config, load_config
from analemma.logger import get_logger, setup_logger
from analemma.scheduler import CaptureScheduler
from analemma.postprocess import run_post_pipeline
from analemma.storage import CaptureMetadata, ImageStorage, StorageError

logger = get_logger(__name__)


# Status file path
STATUS_FILE = Path.home() / ".analemma" / "status.json"


class AnalemmaSystem:
    """Main system class that integrates all components."""

    def __init__(self, config: Config):
        """Initialize the Analemma system.

        Args:
            config: System configuration.
        """
        self.config = config
        self.storage = ImageStorage(config.storage)
        self.scheduler: Optional[CaptureScheduler] = None
        self._running = False

        # Statistics
        self._consecutive_successes = 0
        self._last_capture_time: Optional[str] = None
        self._last_capture_path: Optional[str] = None

        # Load previous status
        self._load_status()

    def _load_status(self) -> None:
        """Load status from status file."""
        if STATUS_FILE.exists():
            try:
                with open(STATUS_FILE, "r") as f:
                    status = json.load(f)
                    self._consecutive_successes = status.get("consecutive_successes", 0)
                    self._last_capture_time = status.get("last_capture_time")
                    self._last_capture_path = status.get("last_capture_path")
            except (json.JSONDecodeError, OSError):
                pass

    def _save_status(self) -> None:
        """Save status to status file."""
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(STATUS_FILE, "w") as f:
                json.dump(
                    {
                        "consecutive_successes": self._consecutive_successes,
                        "last_capture_time": self._last_capture_time,
                        "last_capture_path": self._last_capture_path,
                    },
                    f,
                    indent=2,
                )
        except OSError as e:
            logger.warning(f"Failed to save status: {e}")

    def capture_workflow(self) -> Optional[Path]:
        """Execute the complete capture workflow.

        Returns:
            Path to saved image if successful, None otherwise.
        """
        logger.info("Starting capture workflow")

        # Check storage capacity
        if not self.storage.check_capacity():
            logger.warning("Low storage capacity, but proceeding with capture")

        camera = CameraController(self.config.camera)

        try:
            # Connect to camera
            camera.connect()

            # Capture image
            result = camera.capture()

            # Create metadata
            tz = ZoneInfo(self.config.schedule.timezone)
            capture_time = datetime.fromtimestamp(result.timestamp, tz=tz)

            camera_info = camera.get_info()

            metadata = CaptureMetadata(
                capture_time=capture_time.isoformat(),
                camera_model=camera_info.name,
                exposure_us=result.exposure_us,
                gain=result.gain,
                temperature=result.temperature,
                width=result.width,
                height=result.height,
                timezone=self.config.schedule.timezone,
            )

            # Save image
            save_path = self.storage.save(
                result.image,
                metadata,
                image_type=self.config.camera.image_type,
            )

            # Update statistics
            self._consecutive_successes += 1
            self._last_capture_time = capture_time.isoformat()
            self._last_capture_path = str(save_path)
            self._save_status()

            # Run post-processing pipeline (fault-tolerant)
            if self.config.camera.image_type == "fits":
                run_post_pipeline(
                    fits_path=save_path,
                    base_path=self.config.storage.base_path,
                    sync_config=self.config.sync,
                )

            logger.info(
                f"Capture workflow completed successfully. "
                f"Image saved to: {save_path}"
            )

            return save_path

        except CameraConnectionError as e:
            logger.error(f"Camera connection failed: {e}")
            self._consecutive_successes = 0
            self._save_status()
            return None

        except CaptureError as e:
            logger.error(f"Image capture failed: {e}")
            self._consecutive_successes = 0
            self._save_status()
            return None

        except StorageError as e:
            logger.error(f"Image storage failed: {e}")
            self._consecutive_successes = 0
            self._save_status()
            return None

        except Exception as e:
            logger.error(f"Unexpected error in capture workflow: {e}")
            self._consecutive_successes = 0
            self._save_status()
            return None

        finally:
            camera.disconnect()

    def run_daemon(self) -> None:
        """Run the system as a daemon with scheduled captures."""
        logger.info("Starting Analemma daemon")

        # Set up signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        # Initialize scheduler
        self.scheduler = CaptureScheduler(
            config=self.config.schedule,
            on_capture=self.capture_workflow,
        )

        # Start scheduler
        self.scheduler.start()
        self._running = True

        logger.info("Daemon started, waiting for scheduled captures...")

        # Keep running
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the daemon gracefully."""
        self._running = False
        if self.scheduler is not None:
            self.scheduler.stop()
            self.scheduler = None
        logger.info("Daemon stopped")

    def get_status(self) -> dict:
        """Get current system status.

        Returns:
            Dictionary with system status information.
        """
        storage_info = self.storage.get_storage_info()
        scheduler_status = (
            self.scheduler.get_status()
            if self.scheduler
            else {"running": False, "capture_time": self.config.schedule.capture_time}
        )

        return {
            "daemon": {
                "running": self._running,
            },
            "schedule": scheduler_status,
            "capture": {
                "consecutive_successes": self._consecutive_successes,
                "last_capture_time": self._last_capture_time,
                "last_capture_path": self._last_capture_path,
            },
            "storage": {
                "base_path": str(storage_info.base_path),
                "free_gb": round(storage_info.free_gb, 2),
                "total_gb": round(storage_info.total_gb, 2),
                "image_count": storage_info.image_count,
            },
        }


def run_capture(config_path: Optional[Path] = None) -> Optional[Path]:
    """Run a single capture.

    Args:
        config_path: Path to configuration file.

    Returns:
        Path to saved image if successful.
    """
    config = load_config(config_path)
    setup_logger(config.logging)

    system = AnalemmaSystem(config)
    return system.capture_workflow()


def run_daemon(config_path: Optional[Path] = None) -> None:
    """Run the daemon.

    Args:
        config_path: Path to configuration file.
    """
    config = load_config(config_path)
    setup_logger(config.logging)

    system = AnalemmaSystem(config)
    system.run_daemon()
