import logging
import os
from logging.handlers import TimedRotatingFileHandler


class LogUtil:
    """Logger utility class."""

    _logger = None
    _log_path = None

    @classmethod
    def init_logger(cls, log_dir=None, log_name=None):
        """Initialize the logger."""
        if cls._logger is not None:
            return cls._logger

        # Set the log directory
        if log_dir is None:
            log_dir = os.path.join(os.getcwd(), "logs")

        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # Set the log file base name (fixed name, by the timed rotating handler to archive by day)
        if log_name is None:
            log_name = "test.log"

        cls._log_path = os.path.join(log_dir, log_name)

        # Create the logger
        cls._logger = logging.getLogger("QATools")
        cls._logger.setLevel(logging.DEBUG)

        # File handler: archive by day at midnight, keep the last 7 days
        file_handler = TimedRotatingFileHandler(
            cls._log_path,
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
        )
        # Archive file suffix, like test.log.2026-09-23
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setLevel(logging.DEBUG)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Log format
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Add handlers
        cls._logger.addHandler(file_handler)
        cls._logger.addHandler(console_handler)

        return cls._logger

    @classmethod
    def get_logger(cls):
        """Get the logger."""
        if cls._logger is None:
            cls.init_logger()
        return cls._logger

    @classmethod
    def get_log_path(cls):
        """Get the log file path."""
        return cls._log_path

    @classmethod
    def info(cls, message):
        """Log info message."""
        cls.get_logger().info(message)

    @classmethod
    def debug(cls, message):
        """Log debug message."""
        cls.get_logger().debug(message)

    @classmethod
    def warning(cls, message):
        """Log warning message."""
        cls.get_logger().warning(message)

    @classmethod
    def error(cls, message):
        """Log error message."""
        cls.get_logger().error(message)

    @classmethod
    def critical(cls, message):
        """Log critical message."""
        cls.get_logger().critical(message)


# Quick call method
def get_logger():
    """Quickly get the logger."""
    return LogUtil.get_logger()
