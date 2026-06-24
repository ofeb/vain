from .client import BleedCache
from .file import FileBleedCache

RedisClient = BleedCache | FileBleedCache

__all__ = ["BleedCache", "FileBleedCache", "RedisClient"]
