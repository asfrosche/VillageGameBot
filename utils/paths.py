"""Locations of runtime files: databases and generated data.

Everything the bot writes while running lives under ``runtime/`` (git-ignored).
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR = os.path.join(PROJECT_ROOT, "runtime")
DB_DIR = os.path.join(RUNTIME_DIR, "db")
DATA_DIR = os.path.join(RUNTIME_DIR, "data")
