from __future__ import annotations

# LOCAL MIRROR of mcp_helper.py (status only).

from dataclasses import dataclass


@dataclass
class MCPStatus:
    status: str
    detail: str
    write_gate: bool = False


class RestrictedMCPHelper:
    WRITE_GATE_ENABLED = False

    def __init__(self, helper_cmd: str | None = None):
        self.helper_cmd = helper_cmd

    def status(self) -> MCPStatus:
        return MCPStatus("UNCONFIGURED", "local mirror", False)
