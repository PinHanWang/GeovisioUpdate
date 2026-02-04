"""配置模組"""

try:
    from src.module.TMSUpdate.config.logging_config import (
        LOGGING_CONFIG,
        get_logger,
        setup_logging
    )
    from src.module.TMSUpdate.config.settings import Settings
except ImportError:
    from .logging_config import LOGGING_CONFIG, get_logger, setup_logging
    from .settings import Settings

__all__ = ['LOGGING_CONFIG', 'get_logger', 'setup_logging', 'Settings']