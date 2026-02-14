"""Post-processing module for Analemma Capture System.

Handles FITS-to-TIFF conversion, composite generation, and remote sync.
"""

import subprocess
from pathlib import Path
from typing import Optional

import numpy as np
from astropy.io import fits
from PIL import Image

from analemma.config import SyncConfig
from analemma.logger import get_logger

logger = get_logger(__name__)


class PostProcessError(Exception):
    """Exception raised for post-processing errors."""

    pass


def fits_to_tiff(fits_path: Path) -> Path:
    """Convert a FITS file to TIFF without stretch.

    The raw uint8 pixel values are preserved as-is, ensuring consistent
    brightness across all images regardless of weather conditions.

    Args:
        fits_path: Path to the input FITS file.

    Returns:
        Path to the output TIFF file.

    Raises:
        PostProcessError: If conversion fails.
    """
    tiff_path = fits_path.with_suffix(".tif")

    try:
        with fits.open(fits_path) as hdul:
            data = hdul[0].data

        if data is None:
            raise PostProcessError(f"No image data in FITS file: {fits_path}")

        # FITS stores color as (channels, height, width) -- transpose to (H, W, C)
        if data.ndim == 3:
            data = np.transpose(data, (1, 2, 0))

        # Ensure uint8
        img_data = data.astype(np.uint8)

        # Save as TIFF via Pillow
        if img_data.ndim == 3:
            img = Image.fromarray(img_data, mode="RGB")
        else:
            img = Image.fromarray(img_data, mode="L")

        img.save(tiff_path, "TIFF")
        logger.info(f"TIFF saved: {tiff_path}")
        return tiff_path

    except PostProcessError:
        raise
    except Exception as e:
        raise PostProcessError(f"Failed to convert {fits_path} to TIFF: {e}")


def batch_convert_fits(base_path: Path, force: bool = False) -> list[Path]:
    """Convert all FITS files in a directory tree to TIFF.

    Args:
        base_path: Root directory to search for FITS files.
        force: If True, re-convert even if TIFF already exists.

    Returns:
        List of newly created TIFF paths.
    """
    fits_files = sorted(base_path.rglob("*.fits"))
    converted = []

    for fits_path in fits_files:
        tiff_path = fits_path.with_suffix(".tif")
        if tiff_path.exists() and not force:
            logger.debug(f"Skipping {fits_path.name} (TIFF already exists)")
            continue
        try:
            result = fits_to_tiff(fits_path)
            converted.append(result)
        except PostProcessError as e:
            logger.error(f"Conversion failed: {e}")

    return converted


def create_composite(
    base_path: Path,
    output_path: Optional[Path] = None,
) -> Path:
    """Create analemma composite using lighten blend of all TIFF images.

    Loads images one at a time to minimize memory usage on the Pi.

    Args:
        base_path: Root directory containing TIFF files.
        output_path: Where to save composite. Defaults to base_path/composite.tif.

    Returns:
        Path to the composite image.

    Raises:
        PostProcessError: If composite generation fails.
    """
    if output_path is None:
        output_path = base_path / "composite.tif"

    # Find all TIFF files (exclude composite itself)
    tiff_files = sorted(
        p for p in base_path.rglob("*.tif")
        if p.name != "composite.tif"
    )

    if not tiff_files:
        raise PostProcessError("No TIFF files found for composite")

    logger.info(f"Creating composite from {len(tiff_files)} images")

    # Start with the first image
    composite = np.array(Image.open(tiff_files[0]), dtype=np.uint8)

    # Lighten blend: take the maximum of each pixel across all images
    for tiff_path in tiff_files[1:]:
        try:
            img = np.array(Image.open(tiff_path), dtype=np.uint8)
            if img.shape != composite.shape:
                logger.warning(
                    f"Skipping {tiff_path.name}: shape {img.shape} "
                    f"does not match {composite.shape}"
                )
                continue
            composite = np.maximum(composite, img)
        except Exception as e:
            logger.warning(f"Skipping {tiff_path.name}: {e}")

    # Save composite
    if composite.ndim == 3:
        result_img = Image.fromarray(composite, mode="RGB")
    else:
        result_img = Image.fromarray(composite, mode="L")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result_img.save(output_path, "TIFF")

    # Also save a PNG copy for easy viewing
    png_path = output_path.with_suffix(".png")
    result_img.save(png_path, "PNG")

    logger.info(f"Composite saved: {output_path} (and {png_path})")
    return output_path


def sync_to_remote(base_path: Path, sync_config: SyncConfig) -> bool:
    """Sync files to remote using rclone.

    Args:
        base_path: Local directory to sync from.
        sync_config: Sync configuration.

    Returns:
        True if sync succeeded.
    """
    if not sync_config.enabled:
        logger.debug("Sync is disabled")
        return True

    try:
        # Build include filters based on config
        include_args = []
        if sync_config.files == "tiff":
            include_args = ["--include", "*.tif"]
        elif sync_config.files == "composite":
            include_args = ["--include", "composite.*"]
        # "all" = no filter

        cmd = [
            "rclone", "copy",
            str(base_path),
            sync_config.remote,
            *include_args,
            "--verbose",
        ]

        logger.info(f"Running sync: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            logger.error(f"rclone sync failed: {result.stderr}")
            return False

        if result.stdout:
            logger.debug(f"rclone output: {result.stdout}")

        logger.info("Sync completed successfully")
        return True

    except FileNotFoundError:
        logger.error("rclone not found. Install with: sudo apt install rclone")
        return False
    except subprocess.TimeoutExpired:
        logger.error("Sync timed out after 5 minutes")
        return False
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return False


def run_post_pipeline(
    fits_path: Path,
    base_path: Path,
    sync_config: Optional[SyncConfig] = None,
) -> None:
    """Run the full post-capture pipeline.

    Each step is independent and fault-tolerant.
    Failures are logged but do not block subsequent steps.

    Args:
        fits_path: Path to the just-captured FITS file.
        base_path: Storage base path.
        sync_config: Optional sync configuration (None = skip sync).
    """
    # Step 1: Convert FITS to TIFF
    try:
        fits_to_tiff(fits_path)
        logger.info("Post-process: TIFF conversion complete")
    except Exception as e:
        logger.error(f"Post-process: TIFF conversion failed: {e}")

    # Step 2: Update composite
    try:
        create_composite(base_path)
        logger.info("Post-process: Composite updated")
    except Exception as e:
        logger.error(f"Post-process: Composite generation failed: {e}")

    # Step 3: Sync to remote
    if sync_config and sync_config.enabled:
        try:
            sync_to_remote(base_path, sync_config)
        except Exception as e:
            logger.error(f"Post-process: Sync failed: {e}")
