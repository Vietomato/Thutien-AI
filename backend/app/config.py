import os
from datetime import date

def as_of_date() -> date:
    return date.fromisoformat(os.getenv("AS_OF_DATE", "2026-11-09"))

def data_source() -> str:
    return os.getenv("DATA_SOURCE", "fixture")