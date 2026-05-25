"""Shared DeviceError base + 7 standard subclasses. Every vendor
driver (keysight-scope, terasic-de10lite, usb-hid-tester, and future
contributions) uses these rather than ad-hoc strings so MCP clients
can reliably branch on error_code without parsing English messages.

Exit-code mapping (drivers should implement this in their main()):
    DeviceNotFoundError         -> exit 2
    PermissionError_            -> exit 2
    VendorToolNotFoundError     -> exit 2
    InvalidArgumentError        -> exit 2
    DeviceTimeoutError          -> exit 1
    DeviceProtocolError         -> exit 1
    DeviceBusyError             -> exit 1

Error body shape (always has all 5 fields):
    {
        "success": False,
        "error_code": "<stable machine tag>",
        "error": "<human-readable message>",
        "recoverable": <bool>,
        "last_seen_output": "<tail of subprocess stdout/stderr>",
        "context": {<driver-specific extras>}
    }
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class DeviceError(Exception):
    error_code: str              # stable machine-readable tag
    message: str                 # human-readable
    recoverable: bool = False    # AI hint: should it retry?
    last_seen_output: str = ""   # tail of subprocess stdout/stderr
    context: Optional[Dict[str, Any]] = None  # driver-specific

    def __post_init__(self) -> None:
        # dataclass inheriting from Exception: init Exception with the message
        # so str(exc) still works for normal Python handling.
        Exception.__init__(self, self.message)

    def as_json_body(self) -> Dict[str, Any]:
        return {
            "success": False,
            "error_code": self.error_code,
            "error": self.message,
            "recoverable": self.recoverable,
            "last_seen_output": self.last_seen_output,
            "context": self.context or {},
        }


class DeviceNotFoundError(DeviceError):
    """USB device / hidraw node not present. Recoverable: user re-plugs."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__("device_not_found", message, recoverable=True, **kw)


class PermissionError_(DeviceError):        # Py built-in collision
    """udev/group permission denied. Recoverable if user fixes rules."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__("permission_denied", message, recoverable=True, **kw)


class DeviceTimeoutError(DeviceError):
    """Operation exceeded the per-tool timeout. Possibly recoverable."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__("timeout", message, recoverable=True, **kw)


class DeviceProtocolError(DeviceError):
    """Device returned malformed / unexpected protocol data. Usually
    NOT recoverable — firmware mismatch, protocol drift."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__("protocol_error", message, recoverable=False, **kw)


class VendorToolNotFoundError(DeviceError):
    """Required external binary (quartus_pgm, etc.) not on PATH."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__("vendor_tool_not_found", message, recoverable=True, **kw)


class DeviceBusyError(DeviceError):
    """Another process / session holds the device. Recoverable."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__("device_busy", message, recoverable=True, **kw)


class InvalidArgumentError(DeviceError):
    """Caller-supplied args failed validation. NOT recoverable by retry."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__("invalid_argument", message, recoverable=False, **kw)


# Map error_code → default exit code for drivers to use uniformly.
# Drivers import this and call:
#     sys.exit(EXIT_FOR_CODE[err.error_code])
EXIT_FOR_CODE: Dict[str, int] = {
    "device_not_found":       2,
    "permission_denied":      2,
    "vendor_tool_not_found":  2,
    "invalid_argument":       2,
    "timeout":                1,
    "protocol_error":         1,
    "device_busy":            1,
}
