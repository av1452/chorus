"""Exception hierarchy for harmonyforge."""

from __future__ import annotations


class HarmonyForgeError(Exception):
    """Base class for every error this package raises."""


class RemoteNotFoundError(HarmonyForgeError):
    """No Harmony remote was found on the USB bus."""


class TransportError(HarmonyForgeError):
    """A USB read or write failed."""


class TransportTimeout(TransportError):
    """The remote did not answer within the timeout."""


class UsbBackendMissing(TransportError):
    """pyusb is installed but cannot find libusb, and no hidapi fallback is available."""


class ProtocolError(HarmonyForgeError):
    """The remote sent something we could not make sense of."""


class UnsupportedRemoteError(HarmonyForgeError):
    """The remote was identified but this tool cannot program it yet."""


class VerifyError(HarmonyForgeError):
    """Data read back from the remote did not match what we wrote."""


class ConfigError(HarmonyForgeError):
    """A configuration file is invalid."""


class IRError(HarmonyForgeError):
    """An IR signal could not be parsed, encoded or learned."""


class HubError(HarmonyForgeError):
    """Talking to a Harmony Hub failed."""
