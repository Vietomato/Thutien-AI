from fastapi import FastAPI
from .config import as_of_date
from .f3.api import router as f3_router

app = FastAPI(title="ThuTien AI")
app.include_router(f3_router)

@app.get("/health")
def health():
    return {"status": "ok", "as_of_date": as_of_date().isoformat()}
