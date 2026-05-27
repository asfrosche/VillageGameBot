# utils/data_manager.py
import json
import os

def save_json(file_path, data):
    """Save data to a JSON file"""
    # Ensure directory exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump(data, f)

def load_json(file_path, default=None):
    """Load data from a JSON file"""
    if default is None:
        default = {}
    try:
        with open(file_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
