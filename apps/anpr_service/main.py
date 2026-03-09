from __future__ import annotations

from anpr.infrastructure.settings_manager import SettingsManager
from apps.anpr_service.service import ANPRService


def main() -> None:
    settings = SettingsManager()
    service = ANPRService(settings, event_callback=lambda event: None)
    service.sync_channels()
    service.start_enabled_channels()


if __name__ == "__main__":
    main()
