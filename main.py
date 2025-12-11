from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.database import engine, Base
from app.routers import webhook

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables if not exist (for dev simplicity)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await engine.dispose()

app = FastAPI(title="Fútbol Pronósticos Bot", lifespan=lifespan)

app.include_router(webhook.router)

@app.get("/")
def read_root():
    return {"message": "WhatsApp Bot Backend is Running 🚀"}
