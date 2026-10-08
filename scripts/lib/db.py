import os
import sys

import psycopg
from dotenv import load_dotenv


def connect():
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return psycopg.connect(url)
