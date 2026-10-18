def validate_port(value):
    """Return a valid network port, or raise ValueError."""
    if not isinstance(value, int):
        raise ValueError("port must be an integer")
    if not 0 <= value <= 65536:
        raise ValueError("port is outside the allowed range")
    return value
