import time
import psutil
from typing import Dict
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
                "timestamp": time.time()
            }
        except Exception as e:
            logger.error(f"Error getting system stats: {str(e)}")
            return {}

    @staticmethod
    def log_performance(task_name: str, start_time: float):
        duration = time.time() - start_time
        logger.info(f"Task '{task_name}' completed in {duration:.4f} seconds")
