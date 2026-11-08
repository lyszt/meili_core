"""
Logging utility for Mesly
"""

import sys
from pathlib import Path
from loguru import logger
from typing import Optional


class Logger:
    """
    Centralized logging class using loguru
    """

    _initialized = False

    @classmethod
    def setup(
        cls,
        log_level: str = "INFO",
        log_file: Optional[str] = "logs/mesly.log",
        console: bool = True,
        rotation: str = "10 MB",
        retention: str = "7 days"
    ) -> None:
        """
        Setup logging configuration

        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Path to log file (None to disable file logging)
            console: Enable console logging
            rotation: Log file rotation size
            retention: How long to keep old logs
        """
        if cls._initialized:
            return

        # Remove default handler
        logger.remove()

        # Console logging
        if console:
            logger.add(
                sys.stdout,
                level=log_level,
                format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                       "<level>{level: <8}</level> | "
                       "<cyan>{name}</cyan>:<cyan>{function}</cyan>:"
                       "<cyan>{line}</cyan> - <level>{message}</level>",
                colorize=True
            )

        # File logging
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            logger.add(
                log_file,
                level=log_level,
                format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
                rotation=rotation,
                retention=retention,
                compression="zip"
            )

        cls._initialized = True
        logger.info(f"Logging initialized - Level: {log_level}, File: {log_file}")

    @classmethod
    def get_logger(cls, name: Optional[str] = None):
        """
        Get logger instance

        Args:
            name: Optional logger name for agent

        Returns:
            Logger instance
        """
        if not cls._initialized:
            cls.setup()

        if name:
            return logger.bind(name=name)
        return logger

    @classmethod
    def debug(cls, message: str) -> None:
        """Log debug message"""
        if not cls._initialized:
            cls.setup()
        logger.debug(message)

    @classmethod
    def info(cls, message: str) -> None:
        """Log info message"""
        if not cls._initialized:
            cls.setup()
        logger.info(message)

    @classmethod
    def warning(cls, message: str) -> None:
        """Log warning message"""
        if not cls._initialized:
            cls.setup()
        logger.warning(message)

    @classmethod
    def error(cls, message: str) -> None:
        """Log error message"""
        if not cls._initialized:
            cls.setup()
        logger.error(message)

    @classmethod
    def critical(cls, message: str) -> None:
        """Log critical message"""
        if not cls._initialized:
            cls.setup()
        logger.critical(message)

    @classmethod
    def exception(cls, message: str) -> None:
        """Log exception with traceback"""
        if not cls._initialized:
            cls.setup()
        logger.exception(message)
