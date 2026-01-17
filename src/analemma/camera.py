"""Camera control module for ZWO ASI cameras."""

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from analemma.config import CameraConfig
from analemma.logger import get_logger

# Try to import zwoasi, but allow mock for testing
try:
    import zwoasi as asi

    ASI_AVAILABLE = True
except ImportError:
    ASI_AVAILABLE = False
    asi = None


logger = get_logger(__name__)


class CameraError(Exception):
    """Base exception for camera-related errors."""

    pass


class CameraConnectionError(CameraError):
    """Exception raised when camera connection fails."""

    pass


class CaptureError(CameraError):
    """Exception raised when image capture fails."""

    pass


@dataclass
class CameraInfo:
    """Camera information container."""

    name: str
    camera_id: int
    max_width: int
    max_height: int
    is_color: bool
    bayer_pattern: Optional[str]
    supported_bins: list
    pixel_size: float
    bit_depth: int
    is_usb3: bool


@dataclass
class CaptureResult:
    """Capture result container."""

    image: np.ndarray
    exposure_us: int
    gain: int
    temperature: Optional[float]
    width: int
    height: int
    timestamp: float


class CameraController:
    """Controller class for ZWO ASI cameras."""

    # Retry settings
    MAX_RETRIES = 3
    INITIAL_RETRY_DELAY = 1.0  # seconds

    def __init__(self, config: CameraConfig, camera_index: int = 0):
        """Initialize camera controller.

        Args:
            config: Camera configuration.
            camera_index: Index of camera to use (default: 0 for first camera).
        """
        self.config = config
        self.camera_index = camera_index
        self._camera = None
        self._initialized = False

    def _ensure_asi_initialized(self) -> None:
        """Ensure ASI SDK is initialized."""
        if not ASI_AVAILABLE:
            raise CameraConnectionError(
                "zwoasi library not available. Install with: pip install zwoasi"
            )

        if not self._initialized:
            # Initialize the library with the SDK library path
            # On Raspberry Pi, this is typically in /usr/lib or set via ASI_LIB env
            try:
                asi.init("/usr/lib/libASICamera2.so")
            except asi.ZWO_Error:
                # Already initialized
                pass
            except FileNotFoundError:
                # Try alternative paths
                alt_paths = [
                    "/usr/lib/libASICamera2.so",
                    "/usr/local/lib/libASICamera2.so",
                    "/opt/zwo/lib/libASICamera2.so",
                ]
                for path in alt_paths:
                    try:
                        asi.init(path)
                        break
                    except (FileNotFoundError, Exception):
                        continue
                else:
                    raise CameraConnectionError(
                        "Could not find ASI camera library. "
                        "Please install ZWO ASI SDK or set ASI_LIB environment variable."
                    )
            self._initialized = True

    def connect(self) -> bool:
        """Connect to the camera.

        Returns:
            True if connection successful.

        Raises:
            CameraConnectionError: If connection fails.
        """
        self._ensure_asi_initialized()

        num_cameras = asi.get_num_cameras()
        if num_cameras == 0:
            raise CameraConnectionError("No ZWO ASI cameras found")

        if self.camera_index >= num_cameras:
            raise CameraConnectionError(
                f"Camera index {self.camera_index} out of range. "
                f"Found {num_cameras} camera(s)."
            )

        try:
            self._camera = asi.Camera(self.camera_index)
            self._camera.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, 40)

            # Set initial configuration
            self._apply_config()

            logger.info(f"Connected to camera: {self._camera.get_camera_property()['Name']}")
            return True

        except asi.ZWO_Error as e:
            raise CameraConnectionError(f"Failed to connect to camera: {e}")

    def disconnect(self) -> None:
        """Disconnect from the camera."""
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception as e:
                logger.warning(f"Error closing camera: {e}")
            finally:
                self._camera = None
                logger.info("Camera disconnected")

    def _apply_config(self) -> None:
        """Apply configuration to camera."""
        if self._camera is None:
            return

        try:
            # Set exposure
            self._camera.set_control_value(
                asi.ASI_EXPOSURE, self.config.exposure_us, auto=False
            )

            # Set gain
            self._camera.set_control_value(
                asi.ASI_GAIN, self.config.gain, auto=False
            )

            # Set white balance
            self._camera.set_control_value(asi.ASI_WB_R, self.config.wb_r, auto=False)
            self._camera.set_control_value(asi.ASI_WB_B, self.config.wb_b, auto=False)

            # Set image format based on config
            if self.config.image_type == "raw":
                self._camera.set_image_type(asi.ASI_IMG_RAW16)
            else:
                # Use RGB24 for FITS/PNG
                self._camera.set_image_type(asi.ASI_IMG_RGB24)

            logger.debug(
                f"Camera configured: exposure={self.config.exposure_us}us, "
                f"gain={self.config.gain}"
            )

        except asi.ZWO_Error as e:
            raise CameraError(f"Failed to configure camera: {e}")

    def set_exposure(self, exposure_us: int) -> None:
        """Set exposure time.

        Args:
            exposure_us: Exposure time in microseconds.
        """
        if self._camera is None:
            raise CameraError("Camera not connected")

        self.config.exposure_us = exposure_us
        self._camera.set_control_value(asi.ASI_EXPOSURE, exposure_us, auto=False)
        logger.debug(f"Exposure set to {exposure_us}us")

    def set_gain(self, gain: int) -> None:
        """Set gain.

        Args:
            gain: Gain value (0-600).
        """
        if self._camera is None:
            raise CameraError("Camera not connected")

        if not 0 <= gain <= 600:
            raise ValueError("Gain must be between 0 and 600")

        self.config.gain = gain
        self._camera.set_control_value(asi.ASI_GAIN, gain, auto=False)
        logger.debug(f"Gain set to {gain}")

    def get_info(self) -> CameraInfo:
        """Get camera information.

        Returns:
            CameraInfo object with camera details.

        Raises:
            CameraError: If camera not connected.
        """
        if self._camera is None:
            raise CameraError("Camera not connected")

        try:
            props = self._camera.get_camera_property()

            # Map bayer pattern
            bayer_patterns = {
                0: "RGGB",
                1: "BGGR",
                2: "GRBG",
                3: "GBRG",
            }

            return CameraInfo(
                name=props["Name"],
                camera_id=props["CameraID"],
                max_width=props["MaxWidth"],
                max_height=props["MaxHeight"],
                is_color=props["IsColorCam"],
                bayer_pattern=bayer_patterns.get(props.get("BayerPattern")),
                supported_bins=props.get("SupportedBins", [1]),
                pixel_size=props.get("PixelSize", 0),
                bit_depth=props.get("BitDepth", 8),
                is_usb3=props.get("IsUSB3Camera", False),
            )

        except asi.ZWO_Error as e:
            raise CameraError(f"Failed to get camera info: {e}")

    def capture(self) -> CaptureResult:
        """Capture an image with retry logic.

        Returns:
            CaptureResult containing the image and metadata.

        Raises:
            CaptureError: If capture fails after all retries.
        """
        if self._camera is None:
            raise CameraError("Camera not connected")

        last_error = None
        retry_delay = self.INITIAL_RETRY_DELAY

        for attempt in range(self.MAX_RETRIES):
            try:
                timestamp = time.time()

                # Capture image
                image = self._camera.capture()

                # Get temperature if available
                try:
                    temp_value = self._camera.get_control_value(asi.ASI_TEMPERATURE)
                    temperature = temp_value[0] / 10.0  # Convert to Celsius
                except Exception:
                    temperature = None

                logger.info(
                    f"Image captured: {image.shape}, "
                    f"exposure={self.config.exposure_us}us, gain={self.config.gain}"
                )

                return CaptureResult(
                    image=image,
                    exposure_us=self.config.exposure_us,
                    gain=self.config.gain,
                    temperature=temperature,
                    width=image.shape[1],
                    height=image.shape[0],
                    timestamp=timestamp,
                )

            except asi.ZWO_Error as e:
                last_error = e
                logger.warning(
                    f"Capture attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}"
                )

                if attempt < self.MAX_RETRIES - 1:
                    logger.info(f"Retrying in {retry_delay:.1f}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff

        raise CaptureError(
            f"Capture failed after {self.MAX_RETRIES} attempts: {last_error}"
        )

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False


def list_cameras() -> list[dict]:
    """List all connected ZWO ASI cameras.

    Returns:
        List of camera information dictionaries.
    """
    if not ASI_AVAILABLE:
        return []

    try:
        # Try to initialize if not already done
        try:
            asi.init("/usr/lib/libASICamera2.so")
        except Exception:
            pass

        num_cameras = asi.get_num_cameras()
        cameras = []

        for i in range(num_cameras):
            try:
                cam = asi.Camera(i)
                props = cam.get_camera_property()
                cameras.append(
                    {
                        "index": i,
                        "name": props["Name"],
                        "max_resolution": f"{props['MaxWidth']}x{props['MaxHeight']}",
                        "is_color": props["IsColorCam"],
                    }
                )
                cam.close()
            except Exception as e:
                logger.warning(f"Error getting info for camera {i}: {e}")

        return cameras

    except Exception as e:
        logger.error(f"Error listing cameras: {e}")
        return []
