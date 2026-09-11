import logging
import sys
from .config_manager import config

def setup_logging(name: str) -> logging.Logger:
    """
    Sets up a logger with the specified name and configuration.
    """
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    logger.setLevel(config.LOG_LEVEL)
    return logger

logger = setup_logging("modelapro")
