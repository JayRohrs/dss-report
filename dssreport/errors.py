class DssError(Exception):
    """A problem the user can fix. The message is written in plain words."""


class InputError(DssError):
    """The input data could not be read."""


class ConfigError(DssError):
    """The rules file could not be understood."""


class ConnectionFailed(InputError):
    """A connection to a data source could not be made (address, sign-in, network)."""
