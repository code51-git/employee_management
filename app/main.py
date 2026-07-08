from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
from app.core.rate_limiter import rate_limiter
from app.api.api import api_router
from app.core.config import settings
from app.core.notifications import send_multicast_push
from datetime import date, datetime, time
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.user import UserProfile, User
from sqlalchemy import select, extract


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing system resources...")

    # Start birthday scheduler in background
    birthday_task = asyncio.create_task(send_birthday_notifications())

    yield

    # Clean up on shutdown
    birthday_task.cancel()
    try:
        await birthday_task
    except asyncio.CancelledError:
        pass

    logger.info("Cleaning up system resources...")


async def global_rate_limiter(request: Request = None):
    if request is None:
        return
    if request.headers.get("upgrade", "").lower() == "websocket":
        return
    await rate_limiter(request, limit=100, window=60)


#-----------------------------------------------------------------------------------------------------------

async def send_birthday_notifications():
    while True:
        now = datetime.now()

        next_run = datetime.combine(now.date(), time(9, 0, 0))
        if now >= next_run:
            next_run = datetime.combine(
                date.fromordinal(now.date().toordinal() + 1),
                time(9, 0, 0)
            )

        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        await check_and_notify_birthdays()


async def check_and_notify_birthdays():
    today = date.today()

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(UserProfile, User.fcm_token)
                .join(User, User.id == UserProfile.user_id)
                .where(
                    extract('month', UserProfile.dob) == today.month,
                    extract('day', UserProfile.dob) == today.day,
                    UserProfile.dob.isnot(None)
                )
            )
            birthday_people = result.all()

            if not birthday_people:
                return

            all_tokens_res = await db.execute(
                select(User.fcm_token)
                .where(User.fcm_token.isnot(None))
            )
            all_fcm_tokens = [t for t in all_tokens_res.scalars().all() if t]

            for row in birthday_people:
                profile = row.UserProfile
                birthday_name = f"{profile.first_name} {profile.last_name}"

                if all_fcm_tokens:
                    await send_multicast_push(
                        tokens=all_fcm_tokens,
                        title="🎂 Birthday Today!",
                        body=f"Today is {birthday_name}'s birthday! Wish them well.",
                        data={
                            "event": "birthday_today",
                            "user_id": str(profile.user_id),
                            "employee_name": birthday_name,
                            "department": profile.department or "",
                        }
                    )

                from app.services.chat_manager import manager
                online_user_ids = list(manager.active_connections.keys())
                if online_user_ids:
                    for uid in online_user_ids:
                        await manager.send_personal_message(
                            message={
                                "event": "birthday_today",
                                "employee_name": birthday_name,
                                "department": profile.department,
                                "profile_image_url": profile.profile_image_url,
                                "message": f"🎂 Today is {birthday_name}'s birthday!"
                            },
                            user_id=uid
                        )

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Birthday notification error: {e}")

#-----------------------------------------------------------------------------------------------------------

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Enterprise-grade API for Employee, Attendance, and Payroll Management.",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
    dependencies=[Depends(global_rate_limiter)], 
)

origins = [
    "http://localhost:3000",
    "http://localhost:8003",
    "https://admin.code51.co",
    "https://api.code51.co"
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