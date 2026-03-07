from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock, patch

from packages.anpr_core.channel_runtime import ChannelProcessor


class _FakeBuffer:
    def tobytes(self) -> bytes:
        return b"jpeg"


class _FakeCapture:
    def __init__(self, stop_event, max_reads: int) -> None:
        self._stop_event = stop_event
        self._max_reads = max_reads
        self._reads = 0

    def isOpened(self) -> bool:
        return True

    def read(self):
        self._reads += 1
        if self._reads >= self._max_reads:
            self._stop_event.set()
        return True, f"frame-{self._reads}"

    def release(self) -> None:
        return None


class _FakeMotionDetectorConfig:
    threshold = 0.01
    frame_stride = 1
    activation_frames = 3
    release_frames = 6

    def __init__(self, threshold=0.01, frame_stride=1, activation_frames=3, release_frames=6) -> None:
        self.threshold = threshold
        self.frame_stride = frame_stride
        self.activation_frames = activation_frames
        self.release_frames = release_frames


class ChannelRuntimeMotionGateTests(unittest.TestCase):
    def _run_runtime(
        self,
        channel_overrides: dict,
        *,
        max_reads: int = 3,
        motion_update_value: bool = True,
    ):
        events = []
        processor = ChannelProcessor(lambda event: events.append(event), db_path=":memory:")
        channel = {
            "id": 1,
            "name": "Тест",
            "source": "fake://source",
            "best_shots": 1,
            "cooldown_seconds": 0,
            "ocr_min_confidence": 0.1,
            "size_filter_enabled": True,
            **channel_overrides,
        }
        processor.ensure_channel(channel)
        ctx = processor._contexts[1]

        detector = Mock()
        detector.track.return_value = []
        pipeline = Mock()
        pipeline.process_frame.return_value = []

        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.VideoCapture = lambda *_args, **_kwargs: _FakeCapture(ctx.stop_event, max_reads=max_reads)
        fake_cv2.imencode = lambda *_args, **_kwargs: (True, _FakeBuffer())
        fake_cv2.IMWRITE_JPEG_QUALITY = 80

        fake_pipeline_factory = types.ModuleType("anpr.pipeline.factory")
        fake_pipeline_factory.build_components = lambda **_kwargs: (pipeline, detector)

        motion_detector = Mock()
        motion_detector.update.return_value = motion_update_value

        fake_motion_module = types.ModuleType("anpr.detection.motion_detector")
        fake_motion_module.MotionDetectorConfig = _FakeMotionDetectorConfig
        fake_motion_module.MotionDetector = Mock(return_value=motion_detector)

        with patch.dict(
            sys.modules,
            {
                "cv2": fake_cv2,
                "anpr.pipeline.factory": fake_pipeline_factory,
                "anpr.detection.motion_detector": fake_motion_module,
            },
        ), patch.object(processor._sink, "insert_event", return_value=None):
            processor._run_channel(1)

        return processor, detector, pipeline, motion_detector

    def test_always_mode_runs_detector_and_pipeline(self):
        processor, detector, pipeline, _ = self._run_runtime({"detection_mode": "always"}, max_reads=3)

        self.assertGreaterEqual(detector.track.call_count, 1)
        self.assertEqual(detector.track.call_count, pipeline.process_frame.call_count)
        self.assertGreaterEqual(processor._contexts[1].metrics.processed_frames, 1)

    def test_motion_mode_inactive_skips_detector_and_pipeline_but_updates_preview(self):
        processor, detector, pipeline, motion_detector = self._run_runtime(
            {"detection_mode": "motion"},
            max_reads=4,
            motion_update_value=False,
        )

        self.assertGreaterEqual(motion_detector.update.call_count, 1)
        self.assertEqual(detector.track.call_count, 0)
        self.assertEqual(pipeline.process_frame.call_count, 0)
        self.assertGreaterEqual(processor._contexts[1].metrics.motion_skipped_frames, 1)
        self.assertIsNotNone(processor._contexts[1].metrics.preview_last_frame_at)

    def test_motion_mode_active_runs_detector_and_pipeline(self):
        processor, detector, pipeline, motion_detector = self._run_runtime(
            {"detection_mode": "motion"},
            max_reads=3,
            motion_update_value=True,
        )

        self.assertGreaterEqual(motion_detector.update.call_count, 1)
        self.assertGreaterEqual(detector.track.call_count, 1)
        self.assertEqual(detector.track.call_count, pipeline.process_frame.call_count)
        self.assertGreaterEqual(processor._contexts[1].metrics.processed_frames, 1)

    def test_detector_stride_two_reduces_detector_calls(self):
        _, detector, pipeline, _ = self._run_runtime(
            {"detection_mode": "always", "detector_frame_stride": 2},
            max_reads=5,
        )

        self.assertEqual(detector.track.call_count, 2)
        self.assertEqual(pipeline.process_frame.call_count, 2)

    def test_unknown_detection_mode_logs_warning_and_falls_back_to_always(self):
        with self.assertLogs("packages.anpr_core.channel_runtime", level="WARNING") as captured:
            _, detector, pipeline, _ = self._run_runtime(
                {"detection_mode": "mystery_mode"},
                max_reads=2,
            )

        self.assertGreaterEqual(detector.track.call_count, 1)
        self.assertEqual(detector.track.call_count, pipeline.process_frame.call_count)
        self.assertTrue(any("неизвестный detection_mode" in message.lower() for message in captured.output))


if __name__ == "__main__":
    unittest.main()
