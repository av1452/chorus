"""Exception hierarchy for chorus."""

from __future__ import annotations


class ChorusError(Exception):
    """Base class for every error this package raises."""


class RemoteNotFoundError(ChorusError):
    """No Harmony remote was found on the USB bus."""


class TransportError(ChorusError):
    """A USB read or write failed."""


class TransportTimeout(TransportError):
    """The remote did not answer within the timeout."""


class UsbBackendMissing(TransportError):
    """pyusb is installed but cannot find libusb, and no hidapi fallback is available."""


class ProtocolError(ChorusError):
    """The remote sent something we could not make sense of."""


class UnsupportedRemoteError(ChorusError):
    """The remote was identified but this tool cannot program it yet."""


class VerifyError(ChorusError):
    """Data read back from the remote did not match what we wrote."""


class ConfigError(ChorusError):
    """A configuration file is invalid."""


class IRError(ChorusError):
    """An IR signal could not be parsed, encoded or learned."""


class HubError(ChorusError):
    """Talking to a Harmony Hub failed."""
