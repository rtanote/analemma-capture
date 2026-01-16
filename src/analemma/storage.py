"""Image storage module for Analemma Capture System."""

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from astropy.io import fits
from PIL import Image

from analemma import __version__
from analemma.config import StorageConfig
from analemma.logger import get_logger

logger = get_logger(__name__)


class StorageError(Exception):
    """Exception raised for storage-related errors."""

    pass


@dataclass
class CaptureMetadata:
    """Metadata for a captured image."""

    capture_time: str  # ISO format
    camera_model: str
    exposure_us: int
    gain: int
    temperature: Optional[float]
    width: int
    height: int
    timezone: str
    software_name: str = "analemma-capture"
    software_version: str = __version__

    def to_fits_header(self) -> dict:
        """Convert metadata to FITS header format."""
        header = {
            "DATE-OBS": self.capture_time,
            "INSTRUME": self.camera_model,
            "EXPTIME": self.exposure_us / 1_000_000,  # Convert to seconds
            "GAIN": self.gain,
            "IMAGETYP": "LIGHT",
            "OBJECT": "SUN",
            "TIMESYS": self.timezone,
            "SWCREATE": f"{self.software_name} {self.software_version}",
        }
        if self.temperature is not None:
            header["CCD-TEMP"] = self.temperature
        return header

    def to_dict(self) -> dict:
        """Convert metadata to dictionary for JSON export."""
        return {
            "capture_time": self.capture_time,
            "camera": {
                "model": self.camera_model,
                "exposure_us": self.exposure_us,
                "gain": self.gain,
                "temperature": self.temperature,
            },
            "image": {
                "width": self.width,
                "height": self.height,
            },
            "location": {
                "timezone": self.timezone,
            },
            "software": {
                "name": self.software_name,
                "version": self.software_version,
            },
        }


@dataclass
class StorageInfo:
    """Storage usage information."""

    base_path: Path
    total_bytes: int
    used_bytes: int
    free_bytes: int
    image_count: int

    @property
    def total_gb(self) -> float:
        """Total storage in GB."""
        return self.total_bytes / (1024**3)

    @property
    def used_gb(self) -> float:
        """Used storage in GB."""
        return self.used_bytes / (1024**3)

    @property
    def free_gb(self) -> float:
        """Free storage in GB."""
        return self.free_bytes / (1024**3)

    @property
    def free_mb(self) -> float:
        """Free storage in MB."""
        return self.free_bytes / (1024**2)


class ImageStorage:
    """Image storage manager."""

    def __init__(self, config: StorageConfig):
        """Initialize storage manager.

        Args:
            config: Storage configuration.
        """
        self.config = config
        self._ensure_base_path()

    def _ensure_base_path(self) -> None:
        """Ensure base storage path exists."""
        try:
            self.config.base_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise StorageError(
                f"Permission denied creating storage directory: {self.config.base_path}"
            )
        except OSError as e:
            raise StorageError(f"Error creating storage directory: {e}")

    def _get_save_path(self, timestamp: datetime, extension: str) -> Path:
        """Get the full path for saving an image.

        Args:
            timestamp: Capture timestamp.
            extension: File extension (fits, png).

        Returns:
            Full path for the image file.
        """
        # Generate filename
        filename = f"analemma_{timestamp.strftime('%Y%m%d_%H%M%S')}.{extension}"

        if self.config.monthly_subfolders:
            # Create monthly subfolder path
            subfolder = timestamp.strftime("%Y-%m")
            save_dir = self.config.base_path / subfolder
            save_dir.mkdir(parents=True, exist_ok=True)
        else:
            save_dir = self.config.base_path

        return save_dir / filename

    def save(
        self,
        image: np.ndarray,
        metadata: CaptureMetadata,
        image_type: str = "fits",
    ) -> Path:
        """Save image and metadata.

        Args:
            image: Image data as numpy array.
            metadata: Capture metadata.
            image_type: Image format (fits, png).

        Returns:
            Path to saved image file.

        Raises:
            StorageError: If save fails.
        """
        # Parse capture time
        capture_time = datetime.fromisoformat(metadata.capture_time)

        if image_type == "fits":
            return self._save_fits(image, metadata, capture_time)
        elif image_type == "png":
            return self._save_png(image, metadata, capture_time)
        else:
            raise StorageError(f"Unsupported image type: {image_type}")

    def _save_fits(
        self,
        image: np.ndarray,
        metadata: CaptureMetadata,
        capture_time: datetime,
    ) -> Path:
        """Save image as FITS format.

        Args:
            image: Image data.
            metadata: Capture metadata.
            capture_time: Capture timestamp.

        Returns:
            Path to saved FITS file.
        """
        save_path = self._get_save_path(capture_time, "fits")

        try:
            # Create FITS HDU
            # Note: FITS expects data in (height, width, channels) or (height, width)
            if len(image.shape) == 3:
                # Color image - transpose for FITS convention
                # FITS uses (channels, height, width) for color images
                fits_data = np.transpose(image, (2, 0, 1))
            else:
                fits_data = image

            hdu = fits.PrimaryHDU(fits_data)

            # Add metadata to header
            for key, value in metadata.to_fits_header().items():
                if value is not None:
                    hdu.header[key] = value

            # Add image dimensions
            hdu.header["NAXIS1"] = metadata.width
            hdu.header["NAXIS2"] = metadata.height

            # Write FITS file
            hdu.writeto(save_path, overwrite=True)

            logger.info(f"FITS image saved: {save_path}")
            return save_path

        except Exception as e:
            raise StorageError(f"Failed to save FITS image: {e}")

    def _save_png(
        self,
        image: np.ndarray,
        metadata: CaptureMetadata,
        capture_time: datetime,
    ) -> Path:
        """Save image as PNG format with JSON metadata.

        Args:
            image: Image data.
            metadata: Capture metadata.
            capture_time: Capture timestamp.

        Returns:
            Path to saved PNG file.
        """
        save_path = self._get_save_path(capture_time, "png")
        json_path = save_path.with_suffix(".json")

        try:
            # Convert numpy array to PIL Image
            if len(image.shape) == 3 and image.shape[2] == 3:
                # RGB image
                pil_image = Image.fromarray(image.astype(np.uint8), mode="RGB")
            elif len(image.shape) == 2:
                # Grayscale
                pil_image = Image.fromarray(image.astype(np.uint8), mode="L")
            else:
                raise StorageError(f"Unsupported image shape: {image.shape}")

            # Save PNG
            pil_image.save(save_path, "PNG")

            # Save metadata to JSON
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(metadata.to_dict(), f, indent=2, ensure_ascii=False)

            logger.info(f"PNG image saved: {save_path}")
            logger.info(f"Metadata saved: {json_path}")
            return save_path

        except Exception as e:
            raise StorageError(f"Failed to save PNG image: {e}")

    def get_storage_info(self) -> StorageInfo:
        """Get storage usage information.

        Returns:
            StorageInfo object with current storage stats.
        """
        try:
            usage = shutil.disk_usage(self.config.base_path)

            # Count images
            image_count = 0
            for ext in ("*.fits", "*.png"):
                image_count += len(list(self.config.base_path.rglob(ext)))

            return StorageInfo(
                base_path=self.config.base_path,
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                image_count=image_count,
            )

        except OSError as e:
            logger.error(f"Error getting storage info: {e}")
            return StorageInfo(
                base_path=self.config.base_path,
                total_bytes=0,
                used_bytes=0,
                free_bytes=0,
                image_count=0,
            )

    def check_capacity(self) -> bool:
        """Check if storage capacity is sufficient.

        Returns:
            True if free space is above threshold, False otherwise.
        """
        info = self.get_storage_info()
        threshold_bytes = self.config.min_free_space_mb * 1024 * 1024

        if info.free_bytes < threshold_bytes:
            logger.warning(
                f"Low disk space: {info.free_mb:.1f}MB free "
                f"(threshold: {self.config.min_free_space_mb}MB)"
            )
            return False

        return True

    def list_images(self, year_month: Optional[str] = None) -> list[Path]:
        """List captured images.

        Args:
            year_month: Optional filter by year-month (YYYY-MM format).

        Returns:
            List of image file paths sorted by date.
        """
        if year_month:
            search_path = self.config.base_path / year_month
            if not search_path.exists():
                return []
        else:
            search_path = self.config.base_path

        images = []
        for ext in ("*.fits", "*.png"):
            images.extend(search_path.rglob(ext))

        return sorted(images)
