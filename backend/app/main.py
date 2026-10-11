from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.metrics import router, dashboard_router
from app.config import Settings
from app.services.pinot_client import PinotClient, PinotQueryError
from app.services.kafka_producer import MetricsKafkaProducer, KafkaPublishError

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pinot = PinotClient(str(config.pinot_broker_url),
                            timeout=config.pinot_query_timeout_seconds)
        app.state.pinot = pinot
        kafka = MetricsKafkaProducer(config.kafka_bootstrap_servers, config.kafka_topic,
                                     timeout=config.kafka_publish_timeout_seconds)
        app.state.kafka = kafka
        try:
            await kafka.start()
            yield
        finally:
            try:
                await kafka.stop()
            finally:
                await pinot.close()

    app = FastAPI(title="Real-Time Ride Analytics API", version="0.1.0",
                  lifespan=lifespan)
    app.include_router(router)
    app.include_router(dashboard_router)

    @app.exception_handler(KafkaPublishError)
    async def handle_kafka_error(request: Request, exc: KafkaPublishError):
        logger.warning("Kafka publishing failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=503, content={
            "detail": "Unable to publish metrics event to Kafka."
        })

    @app.exception_handler(PinotQueryError)
    async def handle_pinot_error(request: Request, exc: PinotQueryError):
        logger.warning("Pinot query failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=503, content={
            "detail": "Analytics are temporarily unavailable. Please retry."
        })

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
