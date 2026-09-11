import time
from typing import Dict

import psutil

from modules.logging_manager import logger


class SystemMonitor:
    @staticmethod
    def get_system_stats() -> Dict[str, float]:
        """
        Returns current system statistics.
        """
        try:
            return {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": psutil.virtual_memory().percent,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error("Error getting system stats: %s", e)
            return {}

    @staticmethod
    def log_performance(task_name: str, start_time: float):
        duration = time.time() - start_time
        logger.info("Task '%s' completed in %.4f seconds", task_name, duration)
