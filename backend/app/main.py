from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_clusters,
    routes_download,
    routes_faces,
    routes_persons,
    routes_photos,
    routes_scan,
)
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Face Search", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_scan.router)
app.include_router(routes_clusters.router)
app.include_router(routes_persons.router)
app.include_router(routes_photos.router)
app.include_router(routes_faces.router)
app.include_router(routes_download.router)


@app.get("/health")
def health():
    return {"status": "ok"}
