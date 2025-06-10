import time
import logging
import logging.config
from pathlib import Path
Path("logs").mkdir(parents=True, exist_ok=True)


LOG_FILENAME = f"logs/{time.strftime('%Y-%m-%d_%H-%M-%S')}.log"

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(levelname)s - %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': LOG_FILENAME,
            'encoding': 'utf-8',
            'formatter': 'default'
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'stream': 'ext://sys.stdout'
        },
    },
    'loggers': {
        '': {
            'handlers': ['file', 'console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'matplotlib': {
            'handlers': [],
            'level': 'WARNING',
            'propagate': False,
        },
    }
}


