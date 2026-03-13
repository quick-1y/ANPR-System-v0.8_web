import unittest
from unittest.mock import patch

import numpy as np

from packages.anpr_core.channel_runtime import ChannelProcessor


class _FakeCapture:
    def __init__(self, frame: np.ndarray):
        self._frame = frame

    def isOpened(self):
        return True

    def read(self):
        return True, self._frame.copy()

    def release(self):
        return None

    def set(self, *_args, **_kwargs):
        return True


class _RecordingMotionDetector:
    def __init__(self, *_args, **_kwargs):
        self.frames = []

    def update(self, frame):
        self.frames.append(frame.copy())
        return True


class _DummyDetector:
    def __init__(self, detections):
        self._detections = detections

    def track(self, _frame):
        return list(self._detections)


class _DummyPipeline:
    def __init__(self, stop_event):
        self.stop_event = stop_event
        self.calls = []

    def process_frame(self, frame, detections):
        self.calls.append((frame, list(detections)))
        self.stop_event.set()
        return []


class ChannelRuntimeRoiTests(unittest.TestCase):
    def setUp(self):
        self.processor = ChannelProcessor(event_callback=lambda _event: None)
        self.frame = np.full((100, 100, 3), 255, dtype=np.uint8)
        self.roi_channel = {
            "id": 1,
            "source": "0",
            "detection_mode": "motion",
            "roi_enabled": True,
            "region": {
                "unit": "px",
                "points": [
                    {"x": 0, "y": 0},
                    {"x": 50, "y": 0},
                    {"x": 50, "y": 50},
                    {"x": 0, "y": 50},
                ],
            },
        }

    def _run_once(self, channel, detections):
        self.processor.ensure_channel(channel)
        stop_event = self.processor._contexts[int(channel["id"])].stop_event
        pipeline = _DummyPipeline(stop_event)
        detector = _DummyDetector(detections)
        motion = _RecordingMotionDetector()

        with patch("anpr.pipeline.factory.build_components", return_value=(pipeline, detector)), patch(
            "anpr.detection.motion_detector.MotionDetector", return_value=motion
        ), patch.object(self.processor, "_open_capture", return_value=_FakeCapture(self.frame)):
            self.processor._run_channel(int(channel["id"]))

        return pipeline, motion

    def test_roi_disabled_does_not_filter_detections(self):
        channel = dict(self.roi_channel)
        channel["roi_enabled"] = False
        detections = [{"bbox": [70, 70, 90, 90], "confidence": 0.9}]

        pipeline, motion = self._run_once(channel, detections)

        self.assertEqual(len(pipeline.calls), 1)
        self.assertEqual(pipeline.calls[0][1], detections)
        self.assertTrue(np.array_equal(pipeline.calls[0][0], self.frame))
        self.assertTrue(np.array_equal(motion.frames[0], self.frame))

    def test_roi_enabled_motion_receives_masked_frame(self):
        pipeline, motion = self._run_once(self.roi_channel, [{"bbox": [10, 10, 20, 20]}])

        self.assertEqual(len(pipeline.calls), 1)
        masked_frame = motion.frames[0]
        self.assertEqual(int(masked_frame[75, 75, 0]), 0)
        self.assertEqual(int(masked_frame[10, 10, 0]), 255)

    def test_roi_enabled_filters_detection_outside_roi(self):
        detections = [{"bbox": [70, 70, 90, 90], "confidence": 0.9}]
        pipeline, _motion = self._run_once(self.roi_channel, detections)

        self.assertEqual(len(pipeline.calls), 1)
        self.assertEqual(pipeline.calls[0][1], [])
        self.assertTrue(np.array_equal(pipeline.calls[0][0], self.frame))

    def test_roi_enabled_keeps_detection_inside_roi(self):
        detections = [{"bbox": [10, 10, 20, 20], "confidence": 0.9}]
        pipeline, _motion = self._run_once(self.roi_channel, detections)

        self.assertEqual(len(pipeline.calls), 1)
        self.assertEqual(pipeline.calls[0][1], detections)

    def test_invalid_roi_polygon_falls_back_without_crash(self):
        channel = dict(self.roi_channel)
        channel["region"] = {"unit": "px", "points": [{"x": 0, "y": 0}, {"x": 10, "y": 10}]}
        detections = [{"bbox": [70, 70, 90, 90], "confidence": 0.9}]

        pipeline, motion = self._run_once(channel, detections)

        self.assertEqual(len(pipeline.calls), 1)
        self.assertEqual(pipeline.calls[0][1], detections)
        self.assertTrue(np.array_equal(motion.frames[0], self.frame))


if __name__ == "__main__":
    unittest.main()
