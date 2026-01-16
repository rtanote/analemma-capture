"""Tests for storage module."""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from astropy.io import fits

from analemma.config import StorageConfig
from analemma.storage import CaptureMetadata, ImageStorage, StorageError


@pytest.fixture
def temp_storage_dir():
    """Create temporary storage directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def storage_config(temp_storage_dir):
    """Create storage config with temp directory."""
    return StorageConfig(
        base_path=temp_storage_dir,
        monthly_subfolders=True,
        min_free_space_mb=1,
    )


@pytest.fixture
def sample_image():
    """Create sample RGB image."""
    return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


@pytest.fixture
def sample_metadata():
    """Create sample metadata."""
    return CaptureMetadata(
        capture_time="2026-01-16T12:00:00+09:00",
        camera_model="ZWO ASI224MC",
        exposure_us=1000,
        gain=0,
        temperature=25.5,
        width=640,
        height=480,
        timezone="Asia/Tokyo",
    )


class TestCaptureMetadata:
    """Tests for CaptureMetadata."""

    def test_to_fits_header(self, sample_metadata):
        """Test FITS header conversion."""
        header = sample_metadata.to_fits_header()
        assert header["DATE-OBS"] == "2026-01-16T12:00:00+09:00"
        assert header["INSTRUME"] == "ZWO ASI224MC"
        assert header["EXPTIME"] == 0.001  # 1000us = 0.001s
        assert header["GAIN"] == 0
        assert header["CCD-TEMP"] == 25.5

    def test_to_dict(self, sample_metadata):
        """Test dictionary conversion."""
        data = sample_metadata.to_dict()
        assert data["capture_time"] == "2026-01-16T12:00:00+09:00"
        assert data["camera"]["model"] == "ZWO ASI224MC"
        assert data["camera"]["exposure_us"] == 1000
        assert data["image"]["width"] == 640
        assert data["software"]["name"] == "analemma-capture"


class TestImageStorage:
    """Tests for ImageStorage."""

    def test_init_creates_directory(self, temp_storage_dir):
        """Test that init creates storage directory."""
        storage_path = temp_storage_dir / "images"
        config = StorageConfig(base_path=storage_path)
        storage = ImageStorage(config)
        assert storage_path.exists()

    def test_save_fits(self, storage_config, sample_image, sample_metadata):
        """Test saving FITS image."""
        storage = ImageStorage(storage_config)
        path = storage.save(sample_image, sample_metadata, image_type="fits")

        assert path.exists()
        assert path.suffix == ".fits"
        assert "analemma_20260116_120000.fits" in path.name

        # Verify FITS file content
        with fits.open(path) as hdul:
            header = hdul[0].header
            assert header["INSTRUME"] == "ZWO ASI224MC"
            assert header["EXPTIME"] == 0.001

    def test_save_png(self, storage_config, sample_image, sample_metadata):
        """Test saving PNG image with JSON metadata."""
        storage = ImageStorage(storage_config)
        path = storage.save(sample_image, sample_metadata, image_type="png")

        assert path.exists()
        assert path.suffix == ".png"

        # Check JSON metadata file
        json_path = path.with_suffix(".json")
        assert json_path.exists()

        with open(json_path) as f:
            metadata = json.load(f)
            assert metadata["camera"]["model"] == "ZWO ASI224MC"

    def test_monthly_subfolders(self, storage_config, sample_image, sample_metadata):
        """Test monthly subfolder creation."""
        storage = ImageStorage(storage_config)
        path = storage.save(sample_image, sample_metadata, image_type="fits")

        # Should be in 2026-01 subfolder
        assert "2026-01" in str(path)
        assert (storage_config.base_path / "2026-01").exists()

    def test_no_monthly_subfolders(self, temp_storage_dir, sample_image, sample_metadata):
        """Test saving without monthly subfolders."""
        config = StorageConfig(
            base_path=temp_storage_dir,
            monthly_subfolders=False,
        )
        storage = ImageStorage(config)
        path = storage.save(sample_image, sample_metadata, image_type="fits")

        # Should be directly in base path
        assert path.parent == temp_storage_dir

    def test_unsupported_image_type(self, storage_config, sample_image, sample_metadata):
        """Test error for unsupported image type."""
        storage = ImageStorage(storage_config)
        with pytest.raises(StorageError, match="Unsupported image type"):
            storage.save(sample_image, sample_metadata, image_type="jpeg")

    def test_get_storage_info(self, storage_config):
        """Test getting storage info."""
        storage = ImageStorage(storage_config)
        info = storage.get_storage_info()

        assert info.base_path == storage_config.base_path
        assert info.total_bytes > 0
        assert info.free_bytes > 0
        assert info.image_count == 0

    def test_check_capacity(self, storage_config):
        """Test capacity check."""
        storage = ImageStorage(storage_config)
        # With 1MB threshold, should pass on any modern system
        assert storage.check_capacity() is True

    def test_list_images(self, storage_config, sample_image, sample_metadata):
        """Test listing images."""
        storage = ImageStorage(storage_config)

        # Save some images
        storage.save(sample_image, sample_metadata, image_type="fits")
        storage.save(sample_image, sample_metadata, image_type="png")

        images = storage.list_images()
        assert len(images) == 2

    def test_list_images_filtered(self, storage_config, sample_image, sample_metadata):
        """Test listing images with month filter."""
        storage = ImageStorage(storage_config)
        storage.save(sample_image, sample_metadata, image_type="fits")

        # Filter by correct month
        images = storage.list_images(year_month="2026-01")
        assert len(images) == 1

        # Filter by different month
        images = storage.list_images(year_month="2026-02")
        assert len(images) == 0


class TestGrayscaleImage:
    """Tests for grayscale image handling."""

    def test_save_grayscale_png(self, storage_config, sample_metadata):
        """Test saving grayscale image as PNG."""
        grayscale = np.random.randint(0, 255, (480, 640), dtype=np.uint8)
        storage = ImageStorage(storage_config)
        path = storage.save(grayscale, sample_metadata, image_type="png")
        assert path.exists()

    def test_save_grayscale_fits(self, storage_config, sample_metadata):
        """Test saving grayscale image as FITS."""
        grayscale = np.random.randint(0, 255, (480, 640), dtype=np.uint8)
        storage = ImageStorage(storage_config)
        path = storage.save(grayscale, sample_metadata, image_type="fits")
        assert path.exists()
