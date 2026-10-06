from __future__ import annotations

# LOCAL MIRROR of worker_client_v2.py (interface only).

from team_core import ProviderResult, UNCONFIGURED


class RemoteProviderAdapterV2:
    def __init__(self, name: str, socket_path: str | None = None):
        self.name = name
        self.socket_path = socket_path

    def health(self, force: bool = False) -> str:
        return UNCONFIGURED

    def run(self, prompt, cancel_event, timeout: int = 240) -> ProviderResult:
        return ProviderResult(False, "", self.name, unconfigured=True, error_code=UNCONFIGURED)
