import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.v1.router import router as api_v1_router
from core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("turtlenet")

TurtleNet = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

TurtleNet.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TurtleNet.include_router(api_v1_router, prefix=settings.API_V1_STR)


@TurtleNet.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    log.info(f"{request.method} {request.url.path} → {response.status_code} ({duration:.1f}ms)")
    return response


@TurtleNet.on_event("startup")
async def startup():
    log.info("TurtleNet is up")


@TurtleNet.get("/health")
def health_check():
    return {"status": "ok"}
