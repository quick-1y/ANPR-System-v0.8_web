import unittest

from anpr.stability.runner import StabilitySuite, percentile


class FakeStabilitySuite(StabilitySuite):
    def __init__(self) -> None:
        super().__init__(
            core_url="http://core/api/v1",
            video_url="http://video/api/v1",
            events_url="http://events/api/v1",
        )

    def _probe(self, method, url, payload=None):  # type: ignore[override]
        from anpr.stability.runner import ProbeResult

        if "/health" in url:
            return ProbeResult(ok=True, latency_ms=10.0, status_code=200)
        return ProbeResult(ok=True, latency_ms=20.0, status_code=201)

    def _request_json(self, method, url, payload=None):  # type: ignore[override]
        return {"items": [{"kind": "reconnect_warn"}, {"kind": "timeout_warn"}]}


class StabilityRunnerTests(unittest.TestCase):
    def test_percentile(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(percentile(values, 0), 1.0)
        self.assertEqual(percentile(values, 1), 4.0)
        self.assertAlmostEqual(percentile(values, 0.5), 2.5)

    def test_suite_report(self) -> None:
        suite = FakeStabilitySuite()
        report = suite.run(requests_count=5)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["load"]["requests"], 5)
        self.assertEqual(report["degradation"]["ok"], True)

    def test_soak_report(self) -> None:
        suite = FakeStabilitySuite()
        report = suite.run_soak(duration_minutes=1, interval_seconds=61, requests_per_iteration=3)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["duration_minutes"], 1)
        self.assertEqual(report["requests_per_iteration"], 3)
        self.assertGreaterEqual(report["iterations"], 1)
        self.assertIn("series", report)


if __name__ == "__main__":
    unittest.main()
