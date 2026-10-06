"""Exception hierarchy. Every error raised deliberately by kterminal derives
from :class:`KTerminalError` so callers can distinguish expected failures
from bugs."""


class KTerminalError(Exception):
    """Base class for all kterminal errors."""


class ConfigurationError(KTerminalError):
    """Settings are missing, invalid or unsafe."""


class LiveTradingNotPermittedError(ConfigurationError):
    """An operation required LIVE trading, but the LIVE interlocks are not satisfied."""


class ClockError(KTerminalError, ValueError):
    """Invalid use of a clock (naive datetime, time moving backwards)."""


class RegistryError(KTerminalError):
    """A plug-in registry was used incorrectly."""


class DuplicateRegistrationError(RegistryError):
    """Two different plug-ins were registered under the same key."""


class NotRegisteredError(RegistryError, LookupError):
    """No plug-in is registered under the requested key."""


class LeadershipLostError(KTerminalError):
    """The process lost its leader lock and must stop acting as the leader."""
