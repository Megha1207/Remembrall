def parse_command(message: str):
    """
    Parses message into command and arguments.
    Example:
    "add Buy milk" -> ("add", "Buy milk")
    "list" -> ("list", "")
    """
    parts = message.strip().split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    return command, args
