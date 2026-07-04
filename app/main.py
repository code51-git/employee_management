from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
from app.core.rate_limiter import rate_limiter
from app.api.api import api_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing system resources and connection pools...")
    yield
    logger.info("Cleaning up and closing system resources...")


async def global_rate_limiter(request: Request = None):
    if request is None:
        return
    if request.headers.get("upgrade", "").lower() == "websocket":
        return
    await rate_limiter(request, limit=100, window=60)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Enterprise-grade API for Employee, Attendance, and Payroll Management.",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
    dependencies=[Depends(global_rate_limiter)],  # ← moved here, on the single app
)

origins = [
    "http://localhost:3000",
    "http://localhost:8003",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_unexpected_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled exception on path {request.url.path}: {str(exc)}", exc_info=True
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please contact system administration."},
    )


@app.get("/health", tags=["System Health"], status_code=status.HTTP_200_OK)
async def health_check():
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0",
    }


app.include_router(api_router, prefix=settings.API_V1_STR)