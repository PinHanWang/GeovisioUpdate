# 修改為：
"""配置模組"""

from src.module.TMSUpdate.config.logging_config import (
    LOGGING_CONFIG,
    get_logger,
    setup_logging
)

__all__ = ['LOGGING_CONFIG', 'get_logger', 'setup_logging']