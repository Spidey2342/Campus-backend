from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.database import engine, Base
from app.models import user, reel  # noqa: F401 — imported for side-effect (table creation)
from app.routers import auth, reels, users, discover, notifications, messages

limiter = Limiter(key_func=get_remote_address)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CampusVibe API",
    description="Backend for the CampusVibe student reel platform",
    version="1.0.0"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://campus-loop-peach.vercel.app",
        "http://localhost:5173",  # local dev
        "http://localhost:3000",  # local dev (CRA)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(reels.router)
app.include_router(users.router)
app.include_router(discover.router)
app.include_router(notifications.router)
app.include_router(messages.router)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our end."}
    )

@app.get("/health")
def health_check():
    return {"status": "CampusVibe API is running"}