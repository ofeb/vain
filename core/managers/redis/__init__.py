from .client import VainCache
from .file import FileVainCache

RedisClient = VainCache | FileVainCache

__all__ = ["VainCache", "FileVainCache", "RedisClient"]
