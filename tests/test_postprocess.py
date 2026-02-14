"""Tests for post-processing module."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from astropy.io import fits
from PIL import Image

from analemma.config import SyncConfig
from analemma.postprocess import (
    PostProcessError,
    batch_convert_fits,
    create_composite,
    fits_to_tiff,
    run_post_pipeline,
    sync_to_remote,
)


@pytest.fixture
def temp_dir():
    """Create temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_fits_path(temp_dir):
    """Create a sample FITS file with RGB data."""
    fits_path = temp_dir / "analemma_20260116_120000.fits"
    # Create RGB image data (channels, height, width) as FITS stores it
    data = np.random.randint(0, 255, (3, 480, 640), dtype=np.uint8)
    hdu = fits.PrimaryHDU(data)
    hdu.writeto(fits_path)
    return fits_path


@pytest.fixture
def sample_grayscale_fits_path(temp_dir):
    """Create a sample grayscale FITS file."""
    fits_path = temp_dir / "analemma_20260117_120000.fits"
    data = np.random.randint(0, 255, (480, 640), dtype=np.uint8)
    hdu = fits.PrimaryHDU(data)
    hdu.writeto(fits_path)
    return fits_path


def _create_tiff(path, shape=(480, 640, 3), value=None):
    """Helper to create a TIFF file."""
    if value is not None:
        data = np.full(shape, value, dtype=np.uint8)
    else:
        data = np.random.randint(0, 255, shape, dtype=np.uint8)
    if len(shape) == 3:
        img = Image.fromarray(data, mode="RGB")
    else:
        img = Image.fromarray(data, mode="L")
    img.save(path, "TIFF")
    return data


class TestFitsToTiff:
    """Tests for fits_to_tiff."""

    def test_convert_rgb(self, sample_fits_path):
        """Test converting RGB FITS to TIFF."""
        tiff_path = fits_to_tiff(sample_fits_path)

        assert tiff_path.exists()
        assert tiff_path.suffix == ".tif"
        assert tiff_path.stem == sample_fits_path.stem

        # Verify TIFF is a valid image
        img = Image.open(tiff_path)
        assert img.mode == "RGB"
        assert img.size == (640, 480)

    def test_convert_grayscale(self, sample_grayscale_fits_path):
        """Test converting grayscale FITS to TIFF."""
        tiff_path = fits_to_tiff(sample_grayscale_fits_path)

        assert tiff_path.exists()
        img = Image.open(tiff_path)
        assert img.mode == "L"

    def test_pixel_values_preserved(self, temp_dir):
        """Test that pixel values are preserved without stretch."""
        fits_path = temp_dir / "test.fits"
        # Create known data
        data = np.array([[[100, 150, 200]]], dtype=np.uint8)
        # FITS format: (channels, height, width)
        fits_data = np.transpose(data, (2, 0, 1))
        hdu = fits.PrimaryHDU(fits_data)
        hdu.writeto(fits_path)

        tiff_path = fits_to_tiff(fits_path)
        img = np.array(Image.open(tiff_path))
        np.testing.assert_array_equal(img, data)

    def test_empty_fits_raises_error(self, temp_dir):
        """Test that FITS with no data raises error."""
        fits_path = temp_dir / "empty.fits"
        hdu = fits.PrimaryHDU()
        hdu.writeto(fits_path)

        with pytest.raises(PostProcessError, match="No image data"):
            fits_to_tiff(fits_path)

    def test_nonexistent_file_raises_error(self, temp_dir):
        """Test that nonexistent file raises error."""
        with pytest.raises(PostProcessError, match="Failed to convert"):
            fits_to_tiff(temp_dir / "nonexistent.fits")


class TestBatchConvertFits:
    """Tests for batch_convert_fits."""

    def test_converts_all_fits(self, temp_dir):
        """Test batch conversion of multiple FITS files."""
        # Create multiple FITS files
        for i in range(3):
            fits_path = temp_dir / f"analemma_{i:02d}.fits"
            data = np.random.randint(0, 255, (3, 480, 640), dtype=np.uint8)
            hdu = fits.PrimaryHDU(data)
            hdu.writeto(fits_path)

        converted = batch_convert_fits(temp_dir)
        assert len(converted) == 3
        for p in converted:
            assert p.exists()
            assert p.suffix == ".tif"

    def test_skips_existing_tiff(self, sample_fits_path, temp_dir):
        """Test that existing TIFFs are skipped."""
        # Create a TIFF for the existing FITS
        tiff_path = sample_fits_path.with_suffix(".tif")
        _create_tiff(tiff_path)

        converted = batch_convert_fits(temp_dir)
        assert len(converted) == 0

    def test_force_reconverts(self, sample_fits_path, temp_dir):
        """Test that --force re-converts existing TIFFs."""
        tiff_path = sample_fits_path.with_suffix(".tif")
        _create_tiff(tiff_path)

        converted = batch_convert_fits(temp_dir, force=True)
        assert len(converted) == 1

    def test_empty_directory(self, temp_dir):
        """Test batch convert with no FITS files."""
        converted = batch_convert_fits(temp_dir)
        assert len(converted) == 0

    def test_continues_on_error(self, temp_dir):
        """Test that batch conversion continues after a failure."""
        # Create one valid and one invalid FITS file
        good_path = temp_dir / "good.fits"
        data = np.random.randint(0, 255, (3, 480, 640), dtype=np.uint8)
        hdu = fits.PrimaryHDU(data)
        hdu.writeto(good_path)

        bad_path = temp_dir / "bad.fits"
        hdu = fits.PrimaryHDU()
        hdu.writeto(bad_path)

        converted = batch_convert_fits(temp_dir)
        assert len(converted) == 1


class TestCreateComposite:
    """Tests for create_composite."""

    def test_creates_composite(self, temp_dir):
        """Test composite creation from multiple TIFFs."""
        for i in range(3):
            _create_tiff(temp_dir / f"img_{i}.tif")

        result = create_composite(temp_dir)
        assert result.exists()
        assert result.name == "composite.tif"

        # PNG copy should also exist
        assert result.with_suffix(".png").exists()

    def test_lighten_blend(self, temp_dir):
        """Test that lighten blend takes maximum pixel values."""
        # Create two images with known values
        _create_tiff(temp_dir / "img_a.tif", shape=(2, 2, 3), value=100)
        _create_tiff(temp_dir / "img_b.tif", shape=(2, 2, 3), value=200)

        result = create_composite(temp_dir)
        composite = np.array(Image.open(result))

        # All pixels should be 200 (the maximum)
        assert np.all(composite == 200)

    def test_excludes_composite_from_input(self, temp_dir):
        """Test that composite.tif is excluded from input files."""
        _create_tiff(temp_dir / "img_a.tif", shape=(10, 10, 3), value=50)
        _create_tiff(temp_dir / "composite.tif", shape=(10, 10, 3), value=255)

        result = create_composite(temp_dir)
        composite = np.array(Image.open(result))

        # Should only contain values from img_a (50), not the old composite (255)
        assert np.all(composite == 50)

    def test_custom_output_path(self, temp_dir):
        """Test composite with custom output path."""
        _create_tiff(temp_dir / "img_a.tif")

        output = temp_dir / "custom" / "output.tif"
        result = create_composite(temp_dir, output_path=output)
        assert result == output
        assert output.exists()

    def test_no_tiffs_raises_error(self, temp_dir):
        """Test error when no TIFF files exist."""
        with pytest.raises(PostProcessError, match="No TIFF files found"):
            create_composite(temp_dir)

    def test_skips_mismatched_shapes(self, temp_dir):
        """Test that images with different shapes are skipped."""
        _create_tiff(temp_dir / "img_a.tif", shape=(10, 10, 3), value=50)
        _create_tiff(temp_dir / "img_b.tif", shape=(20, 20, 3), value=200)

        # Should not raise, just skip the mismatched image
        result = create_composite(temp_dir)
        composite = np.array(Image.open(result))
        assert composite.shape == (10, 10, 3)

    def test_handles_subfolders(self, temp_dir):
        """Test composite with TIFF files in subfolders."""
        subfolder = temp_dir / "2026-01"
        subfolder.mkdir()
        _create_tiff(subfolder / "img_a.tif", shape=(10, 10, 3), value=100)
        _create_tiff(temp_dir / "img_b.tif", shape=(10, 10, 3), value=150)

        result = create_composite(temp_dir)
        composite = np.array(Image.open(result))
        assert np.all(composite == 150)


class TestSyncToRemote:
    """Tests for sync_to_remote."""

    def test_disabled_sync(self, temp_dir):
        """Test that disabled sync returns True without running."""
        config = SyncConfig(enabled=False)
        assert sync_to_remote(temp_dir, config) is True

    @patch("analemma.postprocess.subprocess.run")
    def test_successful_sync(self, mock_run, temp_dir):
        """Test successful rclone sync."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        config = SyncConfig(enabled=True, remote="gdrive:analemma", files="tiff")

        assert sync_to_remote(temp_dir, config) is True
        mock_run.assert_called_once()

        # Verify rclone command includes --include *.tif
        call_args = mock_run.call_args[0][0]
        assert "rclone" in call_args
        assert "copy" in call_args
        assert "--include" in call_args
        assert "*.tif" in call_args

    @patch("analemma.postprocess.subprocess.run")
    def test_sync_composite_only(self, mock_run, temp_dir):
        """Test sync with composite-only filter."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        config = SyncConfig(enabled=True, remote="gdrive:analemma", files="composite")

        sync_to_remote(temp_dir, config)

        call_args = mock_run.call_args[0][0]
        assert "--include" in call_args
        assert "composite.*" in call_args

    @patch("analemma.postprocess.subprocess.run")
    def test_sync_all_no_filter(self, mock_run, temp_dir):
        """Test sync with 'all' has no include filter."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        config = SyncConfig(enabled=True, remote="gdrive:analemma", files="all")

        sync_to_remote(temp_dir, config)

        call_args = mock_run.call_args[0][0]
        assert "--include" not in call_args

    @patch("analemma.postprocess.subprocess.run")
    def test_sync_failure(self, mock_run, temp_dir):
        """Test handling of rclone failure."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        config = SyncConfig(enabled=True, remote="gdrive:analemma")

        assert sync_to_remote(temp_dir, config) is False

    @patch("analemma.postprocess.subprocess.run", side_effect=FileNotFoundError)
    def test_rclone_not_found(self, mock_run, temp_dir):
        """Test handling when rclone is not installed."""
        config = SyncConfig(enabled=True, remote="gdrive:analemma")

        assert sync_to_remote(temp_dir, config) is False

    @patch(
        "analemma.postprocess.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="rclone", timeout=300),
    )
    def test_sync_timeout(self, mock_run, temp_dir):
        """Test handling of sync timeout."""
        config = SyncConfig(enabled=True, remote="gdrive:analemma")

        assert sync_to_remote(temp_dir, config) is False


class TestRunPostPipeline:
    """Tests for run_post_pipeline."""

    def test_full_pipeline(self, sample_fits_path, temp_dir):
        """Test full pipeline runs all steps."""
        run_post_pipeline(sample_fits_path, temp_dir)

        # TIFF should be created
        assert sample_fits_path.with_suffix(".tif").exists()
        # Composite should be created
        assert (temp_dir / "composite.tif").exists()

    def test_pipeline_continues_on_tiff_failure(self, temp_dir):
        """Test that pipeline continues even if TIFF conversion fails."""
        # Create a valid TIFF so composite can succeed
        _create_tiff(temp_dir / "existing.tif")

        # Pass a nonexistent FITS path (TIFF conversion will fail)
        run_post_pipeline(temp_dir / "nonexistent.fits", temp_dir)

        # Composite should still be created from existing TIFF
        assert (temp_dir / "composite.tif").exists()

    def test_pipeline_with_sync_disabled(self, sample_fits_path, temp_dir):
        """Test pipeline with sync config but disabled."""
        config = SyncConfig(enabled=False)
        # Should not raise
        run_post_pipeline(sample_fits_path, temp_dir, sync_config=config)

    def test_pipeline_without_sync_config(self, sample_fits_path, temp_dir):
        """Test pipeline with no sync config."""
        # Should not raise
        run_post_pipeline(sample_fits_path, temp_dir, sync_config=None)
