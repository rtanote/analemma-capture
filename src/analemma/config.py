"""Configuration management module for Analemma Capture System."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class CameraConfig:
    """Camera configuration settings."""

    exposure_us: int = 1000  # 1ms for solar photography
    gain: int = 0  # Minimum gain
    image_type: str = "fits"  # fits, png
    wb_r: int = 52  # White balance R
    wb_b: int = 95  # White balance B

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.exposure_us < 1:
            raise ValueError("exposure_us must be positive")
        if not 0 <= self.gain <= 300:
            raise ValueError("gain must be between 0 and 300")
        if self.image_type not in ("fits", "png", "raw"):
            raise ValueError("image_type must be 'fits', 'png', or 'raw'")


@dataclass
class ScheduleConfig:
    """Schedule configuration settings."""

    capture_time: str = "12:00"  # HH:MM format
    timezone: str = "Asia/Tokyo"

    def __post_init__(self) -> None:
        """Validate configuration values."""
        try:
            parts = self.capture_time.split(":")
            if len(parts) != 2:
                raise ValueError()
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError()
        except (ValueError, AttributeError):
            raise ValueError(
                f"capture_time must be in HH:MM format (24-hour), got '{self.capture_time}'"
            )


@dataclass
class StorageConfig:
    """Storage configuration settings."""

    base_path: Path = field(default_factory=lambda: Path("/home/pi/analemma/images"))
    monthly_subfolders: bool = True
    min_free_space_mb: int = 1024

    def __post_init__(self) -> None:
        """Convert string path to Path object if necessary."""
        if isinstance(self.base_path, str):
            self.base_path = Path(self.base_path)
        if self.min_free_space_mb < 0:
            raise ValueError("min_free_space_mb must be non-negative")


@dataclass
class LoggingConfig:
    """Logging configuration settings."""

    level: str = "INFO"
    file: Optional[Path] = field(default_factory=lambda: Path("/var/log/analemma/capture.log"))
    max_size_mb: int = 10
    backup_count: int = 5

    def __post_init__(self) -> None:
        """Validate and convert configuration values."""
        if isinstance(self.file, str):
            self.file = Path(self.file)
        valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        if self.level.upper() not in valid_levels:
            raise ValueError(f"level must be one of {valid_levels}")
        self.level = self.level.upper()


@dataclass
class Config:
    """Main configuration container."""

    camera: CameraConfig = field(default_factory=CameraConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Create Config from dictionary."""
        camera_data = data.get("camera", {})
        schedule_data = data.get("schedule", {})
        storage_data = data.get("storage", {})
        logging_data = data.get("logging", {})

        return cls(
            camera=CameraConfig(**camera_data),
            schedule=ScheduleConfig(**schedule_data),
            storage=StorageConfig(**storage_data),
            logging=LoggingConfig(**logging_data),
        )

    def to_dict(self) -> dict:
        """Convert Config to dictionary."""
        return {
            "camera": {
                "exposure_us": self.camera.exposure_us,
                "gain": self.camera.gain,
                "image_type": self.camera.image_type,
                "wb_r": self.camera.wb_r,
                "wb_b": self.camera.wb_b,
            },
            "schedule": {
                "capture_time": self.schedule.capture_time,
                "timezone": self.schedule.timezone,
            },
            "storage": {
                "base_path": str(self.storage.base_path),
                "monthly_subfolders": self.storage.monthly_subfolders,
                "min_free_space_mb": self.storage.min_free_space_mb,
            },
            "logging": {
                "level": self.logging.level,
                "file": str(self.logging.file) if self.logging.file else None,
                "max_size_mb": self.logging.max_size_mb,
                "backup_count": self.logging.backup_count,
            },
        }


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load configuration from YAML file.

    Args:
        config_path: Path to configuration file. If None, uses default path.

    Returns:
        Config object with loaded or default values.
    """
    # Default config paths to try
    if config_path is None:
        default_paths = [
            Path("config/config.yaml"),
            Path("/etc/analemma/config.yaml"),
            Path.home() / ".config" / "analemma" / "config.yaml",
        ]
        for path in default_paths:
            if path.exists():
                config_path = path
                break

    if config_path is None or not config_path.exists():
        # Return default configuration
        return Config()

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        return Config()

    return Config.from_dict(data)


def save_config(config: Config, config_path: Path) -> None:
    """Save configuration to YAML file.

    Args:
        config: Config object to save.
        config_path: Path to save configuration file.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config.to_dict(), f, default_flow_style=False, allow_unicode=True)
