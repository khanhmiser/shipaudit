"""Kết nối MongoDB dùng chung."""
from functools import lru_cache

from pymongo import MongoClient

from common import config


@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    return MongoClient(config.MONGO_URI)


def get_db():
    return get_client()[config.MONGO_DB]
