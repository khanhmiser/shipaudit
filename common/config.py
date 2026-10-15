"""Đọc cấu hình từ biến môi trường / .env."""
import os

from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "shipaudit")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change-me")
INGEST_DELAY_MS = int(os.getenv("INGEST_DELAY_MS", "0"))
INGEST_FAIL_RATE = float(os.getenv("INGEST_FAIL_RATE", "0"))
