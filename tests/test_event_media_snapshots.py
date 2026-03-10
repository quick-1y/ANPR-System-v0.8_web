from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from fastapi.responses import FileResponse

from app.api.main import get_event_media
from packages.anpr_core.channel_runtime import ChannelProcessor


class _FakeCapture:
    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame
        self._released = False

    def isOpened(self) -> bool:  # noqa: N802
        return True

    def read(self):
        return True, self._frame.copy()

    def release(self) -> None:
        self._released = True


class _FakeDetector:
    def __init__(self, detections):
        self._detections = detections

    def track(self, frame):
        return [dict(item) for item in self._detections]


class _FakePipeline:
    def __init__(self, results):
        self._results = results

    def process_frame(self, frame, detections):
        return [dict(item) for item in self._results]


class EventMediaSnapshotTests(unittest.TestCase):
    def _make_processor(self, screenshots_dir: str) -> ChannelProcessor:
        return ChannelProcessor(
            event_callback=lambda event: None,
            plate_settings={},
            storage_settings={
                "postgres_dsn": "postgresql://user:pass@localhost:5432/anpr",
                "screenshots_dir": screenshots_dir,
            },
        )

    def test_event_saves_frame_and_plate_and_passes_paths_to_sink(self) -> None:
        frame = np.full((80, 160, 3), 255, dtype=np.uint8)
        detection = {"bbox": [20, 10, 60, 30], "text": "A123BC", "confidence": 0.91, "country": "RU", "direction": "IN"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            processor = self._make_processor(tmp_dir)
            processor._sink = Mock()

            channel = {"id": 1, "name": "Канал 1", "source": "cam://1", "detection_mode": "always", "detector_frame_stride": 1}
            processor.ensure_channel(channel)

            def stop_on_event(event):
                processor._contexts[1].stop_event.set()

            processor._event_callback = stop_on_event

            with patch("anpr.pipeline.factory.build_components", return_value=(_FakePipeline([detection]), _FakeDetector([detection]))), patch(
                "packages.anpr_core.channel_runtime.cv2.VideoCapture", return_value=_FakeCapture(frame)
            ):
                processor._run_channel(1)

            kwargs = processor._sink.insert_event.call_args.kwargs
            self.assertIsNotNone(kwargs["frame_path"])
            self.assertIsNotNone(kwargs["plate_path"])
            self.assertTrue(Path(kwargs["frame_path"]).is_file())
            self.assertTrue(Path(kwargs["plate_path"]).is_file())

    def test_event_is_not_lost_when_plate_crop_invalid(self) -> None:
        frame = np.full((50, 50, 3), 120, dtype=np.uint8)
        detection = {"bbox": [10, 10, 10, 20], "text": "B777BB", "confidence": 0.8, "country": "RU", "direction": "OUT"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            processor = self._make_processor(tmp_dir)
            processor._sink = Mock()
            processor.ensure_channel({"id": 2, "name": "Канал 2", "source": "cam://2", "detection_mode": "always", "detector_frame_stride": 1})
            processor._event_callback = lambda event: processor._contexts[2].stop_event.set()

            with patch("anpr.pipeline.factory.build_components", return_value=(_FakePipeline([detection]), _FakeDetector([detection]))), patch(
                "packages.anpr_core.channel_runtime.cv2.VideoCapture", return_value=_FakeCapture(frame)
            ):
                processor._run_channel(2)

            kwargs = processor._sink.insert_event.call_args.kwargs
            self.assertIsNotNone(kwargs["frame_path"])
            self.assertIsNone(kwargs["plate_path"])
            self.assertTrue(Path(kwargs["frame_path"]).is_file())

    def test_api_media_endpoints_return_saved_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            frame_path = Path(tmp_dir) / "frame.jpg"
            plate_path = Path(tmp_dir) / "plate.jpg"
            frame_path.write_bytes(b"frame")
            plate_path.write_bytes(b"plate")

            with patch("app.api.main._fetch_event_by_id", return_value={"frame_path": str(frame_path), "plate_path": str(plate_path)}):
                frame_response = get_event_media(101, "frame")
                plate_response = get_event_media(101, "plate")

            self.assertIsInstance(frame_response, FileResponse)
            self.assertIsInstance(plate_response, FileResponse)
            self.assertEqual(Path(frame_response.path), frame_path)
            self.assertEqual(Path(plate_response.path), plate_path)


if __name__ == "__main__":
    unittest.main()
