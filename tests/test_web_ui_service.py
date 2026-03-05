import unittest

from anpr.web_ui.server import build_runtime_config, resolve_proxy_target


class WebUIServiceTests(unittest.TestCase):
    def test_build_runtime_config_normalizes_trailing_slashes(self) -> None:
        config = build_runtime_config(
            core_base_url="http://127.0.0.1:8080/api/v1/",
            video_base_url="http://127.0.0.1:8090/api/v1///",
            events_base_url="http://127.0.0.1:8100/api/v1/",
        )

        self.assertEqual(config["core_base_url"], "http://127.0.0.1:8080/api/v1")
        self.assertEqual(config["video_base_url"], "http://127.0.0.1:8090/api/v1")
        self.assertEqual(config["events_base_url"], "http://127.0.0.1:8100/api/v1")


    def test_resolve_proxy_target(self) -> None:
        config = build_runtime_config(
            core_base_url="http://127.0.0.1:8080/api/v1/",
            video_base_url="http://127.0.0.1:8090/api/v1///",
            events_base_url="http://127.0.0.1:8100/api/v1/",
        )

        self.assertEqual(
            resolve_proxy_target('/api/proxy/core/channels?limit=5', config),
            ('http://127.0.0.1:8080/api/v1', '/channels?limit=5'),
        )
        self.assertEqual(
            resolve_proxy_target('/api/proxy/video/video/streams', config),
            ('http://127.0.0.1:8090/api/v1', '/video/streams'),
        )
        self.assertEqual(
            resolve_proxy_target('/api/proxy/events/events/subscribe', config),
            ('http://127.0.0.1:8100/api/v1', '/events/subscribe'),
        )
        self.assertIsNone(resolve_proxy_target('/api/unknown', config))


if __name__ == "__main__":
    unittest.main()
