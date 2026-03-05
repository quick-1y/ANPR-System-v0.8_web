#!/usr/bin/env python3
from __future__ import annotations

import argparse

from anpr.web_ui.server import run_server


def main() -> None:
    """Совместимый entrypoint: по умолчанию запускает Web UI."""

    parser = argparse.ArgumentParser(description="ANPR Web UI (default entrypoint)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8110, type=int)
    parser.add_argument("--core-base-url", default="http://127.0.0.1:8080/api/v1")
    parser.add_argument("--video-base-url", default="http://127.0.0.1:8090/api/v1")
    parser.add_argument("--events-base-url", default="http://127.0.0.1:8100/api/v1")
    args = parser.parse_args()

    run_server(
        host=args.host,
        port=args.port,
        core_base_url=args.core_base_url,
        video_base_url=args.video_base_url,
        events_base_url=args.events_base_url,
    )


if __name__ == "__main__":
    main()
