"""Tests for camera module."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from analemma.camera import (
    CameraConnectionError,
    CameraController,
    CameraError,
    CameraInfo,
    CaptureError,
    CaptureResult,
)
from analemma.config import CameraConfig


@pytest.fixture
def camera_config():
    """Create camera configuration."""
    return CameraConfig(
        exposure_us=1000,
        gain=0,
        image_type="fits",
        wb_r=52,
        wb_b=95,
    )


class TestCameraControllerNoHardware:
    """Tests for CameraController without actual hardware."""

    def test_init(self, camera_config):
        """Test controller initialization."""
        controller = CameraController(camera_config)
        assert controller.config == camera_config
        assert controller.camera_index == 0
        assert controller._camera is None

    def test_connect_no_library(self, camera_config):
        """Test connection when zwoasi library is not available."""
        with patch("analemma.camera.ASI_AVAILABLE", False):
            controller = CameraController(camera_config)
            with pytest.raises(CameraConnectionError, match="zwoasi library not available"):
                controller.connect()

    def test_capture_not_connected(self, camera_config):
        """Test capture when not connected."""
        controller = CameraController(camera_config)
        with pytest.raises(CameraError, match="Camera not connected"):
            controller.capture()

    def test_get_info_not_connected(self, camera_config):
        """Test get_info when not connected."""
        controller = CameraController(camera_config)
        with pytest.raises(CameraError, match="Camera not connected"):
            controller.get_info()

    def test_set_exposure_not_connected(self, camera_config):
        """Test set_exposure when not connected."""
        controller = CameraController(camera_config)
        with pytest.raises(CameraError, match="Camera not connected"):
            controller.set_exposure(2000)

    def test_set_gain_not_connected(self, camera_config):
        """Test set_gain when not connected."""
        controller = CameraController(camera_config)
        with pytest.raises(CameraError, match="Camera not connected"):
            controller.set_gain(50)

    def test_set_gain_invalid_value(self, camera_config):
        """Test set_gain with invalid value."""
        controller = CameraController(camera_config)
        controller._camera = MagicMock()  # Pretend connected
        with pytest.raises(ValueError, match="Gain must be between"):
            controller.set_gain(500)


class TestCameraControllerMocked:
    """Tests for CameraController with mocked hardware."""

    @pytest.fixture
    def mock_asi(self):
        """Create mocked asi module."""
        with patch("analemma.camera.asi") as mock_asi:
            mock_asi.ASI_EXPOSURE = 1
            mock_asi.ASI_GAIN = 2
            mock_asi.ASI_WB_R = 3
            mock_asi.ASI_WB_B = 4
            mock_asi.ASI_BANDWIDTHOVERLOAD = 5
            mock_asi.ASI_TEMPERATURE = 6
            mock_asi.ASI_IMG_RGB24 = 0
            mock_asi.ASI_IMG_RAW16 = 1
            mock_asi.get_num_cameras.return_value = 1
            yield mock_asi

    @pytest.fixture
    def mock_camera(self, mock_asi):
        """Create mocked camera instance."""
        camera = MagicMock()
        camera.get_camera_property.return_value = {
            "Name": "ZWO ASI224MC",
            "CameraID": 0,
            "MaxWidth": 1304,
            "MaxHeight": 976,
            "IsColorCam": True,
            "BayerPattern": 0,
            "SupportedBins": [1, 2],
            "PixelSize": 3.75,
            "BitDepth": 12,
            "IsUSB3Camera": True,
        }
        camera.capture.return_value = np.random.randint(
            0, 255, (976, 1304, 3), dtype=np.uint8
        )
        camera.get_control_value.return_value = (250, False)  # Temperature
        mock_asi.Camera.return_value = camera
        return camera

    def test_connect_success(self, camera_config, mock_asi, mock_camera):
        """Test successful connection."""
        with patch("analemma.camera.ASI_AVAILABLE", True):
            controller = CameraController(camera_config)
            controller._initialized = True  # Skip init
            result = controller.connect()
            assert result is True

    def test_connect_no_cameras(self, camera_config, mock_asi):
        """Test connection when no cameras found."""
        mock_asi.get_num_cameras.return_value = 0
        with patch("analemma.camera.ASI_AVAILABLE", True):
            controller = CameraController(camera_config)
            controller._initialized = True
            with pytest.raises(CameraConnectionError, match="No ZWO ASI cameras found"):
                controller.connect()

    def test_capture_success(self, camera_config, mock_asi, mock_camera):
        """Test successful capture."""
        with patch("analemma.camera.ASI_AVAILABLE", True):
            controller = CameraController(camera_config)
            controller._initialized = True
            controller._camera = mock_camera

            result = controller.capture()

            assert isinstance(result, CaptureResult)
            assert result.image.shape == (976, 1304, 3)
            assert result.exposure_us == 1000
            assert result.gain == 0
            assert result.temperature == 25.0  # 250 / 10

    def test_capture_retry(self, camera_config, mock_asi, mock_camera):
        """Test capture with retry on failure."""
        mock_camera.capture.side_effect = [
            Exception("First failure"),
            Exception("Second failure"),
            np.random.randint(0, 255, (976, 1304, 3), dtype=np.uint8),
        ]

        with patch("analemma.camera.ASI_AVAILABLE", True):
            with patch("time.sleep"):  # Skip actual sleep
                controller = CameraController(camera_config)
                controller._initialized = True
                controller._camera = mock_camera

                result = controller.capture()
                assert result is not None
                assert mock_camera.capture.call_count == 3

    def test_capture_all_retries_fail(self, camera_config, mock_asi, mock_camera):
        """Test capture when all retries fail."""
        mock_asi.ZWO_Error = Exception
        mock_camera.capture.side_effect = Exception("Persistent failure")

        with patch("analemma.camera.ASI_AVAILABLE", True):
            with patch("time.sleep"):
                controller = CameraController(camera_config)
                controller._initialized = True
                controller._camera = mock_camera

                with pytest.raises(CaptureError, match="failed after 3 attempts"):
                    controller.capture()

    def test_get_info(self, camera_config, mock_asi, mock_camera):
        """Test getting camera info."""
        with patch("analemma.camera.ASI_AVAILABLE", True):
            controller = CameraController(camera_config)
            controller._camera = mock_camera

            info = controller.get_info()

            assert isinstance(info, CameraInfo)
            assert info.name == "ZWO ASI224MC"
            assert info.max_width == 1304
            assert info.max_height == 976
            assert info.is_color is True

    def test_context_manager(self, camera_config, mock_asi, mock_camera):
        """Test using controller as context manager."""
        with patch("analemma.camera.ASI_AVAILABLE", True):
            controller = CameraController(camera_config)
            controller._initialized = True

            with controller as cam:
                assert cam._camera is not None

            mock_camera.close.assert_called_once()

    def test_disconnect(self, camera_config, mock_asi, mock_camera):
        """Test disconnecting from camera."""
        with patch("analemma.camera.ASI_AVAILABLE", True):
            controller = CameraController(camera_config)
            controller._camera = mock_camera

            controller.disconnect()

            mock_camera.close.assert_called_once()
            assert controller._camera is None


class TestCaptureResult:
    """Tests for CaptureResult dataclass."""

    def test_create_capture_result(self):
        """Test creating CaptureResult."""
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        result = CaptureResult(
            image=image,
            exposure_us=1000,
            gain=0,
            temperature=25.0,
            width=640,
            height=480,
            timestamp=1234567890.0,
        )
        assert result.width == 640
        assert result.height == 480


class TestCameraInfo:
    """Tests for CameraInfo dataclass."""

    def test_create_camera_info(self):
        """Test creating CameraInfo."""
        info = CameraInfo(
            name="ZWO ASI224MC",
            camera_id=0,
            max_width=1304,
            max_height=976,
            is_color=True,
            bayer_pattern="RGGB",
            supported_bins=[1, 2],
            pixel_size=3.75,
            bit_depth=12,
            is_usb3=True,
        )
        assert info.name == "ZWO ASI224MC"
        assert info.is_color is True
