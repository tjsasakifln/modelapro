import redis
import json
from typing import Any, Optional
from .config_manager import config
from .logging_manager import logger

class CacheManager:
    def __init__(self):
        try:
            self.redis = redis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                decode_responses=True
            )
        except Exception as e:
            logger.warning(f"Redis connection failed: {str(e)}. Caching disabled.")
            self.redis = None
            
    def set(self, key: str, value: Any, expiration: int = 3600) -> bool:
        if not self.redis:
            return False
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            self.redis.setex(key, expiration, value)
            return True
        except Exception as e:
            logger.error(f"Cache set error: {str(e)}")
            return False
            
    def get(self, key: str) -> Optional[Any]:
        if not self.redis:
            return None
        try:
            value = self.redis.get(key)
            if value:
                try:
                    return json.loads(value)
                except:
                    return value
            return None
        except Exception as e:
            logger.error(f"Cache get error: {str(e)}")
            return None
