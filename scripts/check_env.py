#!/usr/bin/env python3
import os
import sys


REQUIRED = [
    "SECRET_KEY",
    "DATABASE_URL",
    "APP_BASE_URL",
    "DEFAULT_LANGUAGE",
    "SECONDARY_LANGUAGE",
]

missing = [key for key in REQUIRED if not os.getenv(key)]
if missing:
    print("Missing required environment variables:")
    for key in missing:
        print(f"- {key}")
    sys.exit(1)

print("Environment check passed.")

