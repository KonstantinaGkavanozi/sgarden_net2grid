import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import settings
from database import init_indexes
from seed import seed_data
from routes.auth import router as auth_router
from routes.products import router as products_router
from routes.users import router as users_router
from routes.search import router as search_router

# CODE QUALITY ISSUE: unused variable
APP_NAME = "SGarden Inventory API"
DEBUG_MODE = True
unused_config = {"key": "value", "secret": "not-so-secret"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting SGarden API...")
    await init_indexes()
    await seed_data()
    print("SGarden API started successfully")
    yield
    # Shutdown
    print("Shutting down SGarden API...")


app = FastAPI(
    title="SGarden API",
    description="Inventory Management API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth_router)
app.include_router(products_router)
app.include_router(users_router)
app.include_router(search_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
