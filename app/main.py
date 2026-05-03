from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.database import engine, Base
from app.models import user, reel
from app.routers import auth, reels, users, discover

# Limiter uses the client's IP address to track requests
# get_remote_address extracts the IP from the request
limiter = Limiter(key_func=get_remote_address)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CampusVibe API",
    description="Backend for the CampusVibe student reel platform",
    version="1.0.0"
)

# Attach limiter to the app
app.state.limiter = limiter

# When rate limit is exceeded — return a clean JSON error
# instead of a crash
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",          # local dev
        "http://localhost:3000",          # local dev
        "https://campus-loop-peach.vercel.app/",    # 👈 replace with your real Vercel URL
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(reels.router)
app.include_router(users.router)
app.include_router(discover.router)

# Global error handler — catches ANY unhandled exception
# Instead of a raw 500 crash, returns a clean JSON message
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    # Print full traceback to server logs for debugging
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Something went wrong on our end. Please try again.",
          
        }
    )

@app.get("/health")
def health_check():
    return {"status": "CampusVibe API is running"}