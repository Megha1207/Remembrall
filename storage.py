import pickle
from pathlib import Path

STORAGE_FILE = Path("storage.pkl")

def save_data(data):
    with open(STORAGE_FILE, "wb") as f:
        pickle.dump(data, f)

def load_data():
    if not STORAGE_FILE.exists():
        return {}
    try:
        with open(STORAGE_FILE, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Warning: Could not load data from {STORAGE_FILE}: {e}")
        return {}

def get_phone_for_task(task_name: str) -> str | None:
    data = load_data()
    return data.get(task_name)

def set_phone_for_task(task_name: str, phone_number: str):
    data = load_data()
    data[task_name] = phone_number
    save_data(data)
