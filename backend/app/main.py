from fastapi import FastAPI
from .config import as_of_date

app = FastAPI(title="ThuTien AI")

@app.get("/health")
def health():
    return {"status": "ok", "as_of_date": as_of_date().isoformat()}