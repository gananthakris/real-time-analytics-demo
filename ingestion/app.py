"""
FastAPI Ingestion API for Real-Time Analytics Pipeline
Handles event ingestion with rate limiting and Kafka publishing
"""

import json
import time
from datetime import datetime
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response
import redis
from kafka import KafkaProducer
from pythonjsonlogger import jsonlogger
import logging
import hashlib


# Logging setup
logger = logging.getLogger(__name__)
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter()
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# Prometheus metrics
events_received = Counter('events_received_total', 'Total events received', ['customer_id', 'event_type'])
events_published = Counter('events_published_total', 'Total events published to Kafka', ['customer_id'])
events_dropped = Counter('events_dropped_total', 'Total events dropped', ['customer_id', 'reason'])
ingestion_latency = Histogram('ingestion_latency_seconds', 'Ingestion latency in seconds', ['customer_id'])

# Global connections
kafka_producer = None
redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown"""
    global kafka_producer, redis_client

    # Startup
    logger.info("Starting ingestion API...")

    # Initialize Kafka producer
    kafka_producer = KafkaProducer(
        bootstrap_servers=['localhost:9092'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        compression_type='gzip',
        acks='all',  # Wait for all replicas
        retries=3,
        max_in_flight_requests_per_connection=1
    )
    logger.info("Kafka producer initialized")

    # Initialize Redis client
    redis_client = redis.Redis(
        host='localhost',
        port=6379,
        db=0,
        decode_responses=True
    )
    logger.info("Redis client initialized")

    yield

    # Shutdown
    logger.info("Shutting down ingestion API...")
    if kafka_producer:
        kafka_producer.flush()
        kafka_producer.close()
    if redis_client:
        redis_client.close()


app = FastAPI(
    title="Real-Time Analytics Ingestion API",
    description="High-throughput event ingestion with multi-tenant support",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models
class Event(BaseModel):
    customer_id: str = Field(..., description="Customer/tenant identifier")
    visitor_id: str = Field(..., description="Anonymous visitor identifier")
    user_id: Optional[str] = Field(None, description="Authenticated user identifier")
    session_id: str = Field(..., description="Session identifier")
    event_type: str = Field(..., description="Event type (page_view, click, etc)")
    event_name: str = Field(..., description="Human-readable event name")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Event properties")
    page_url: Optional[str] = None
    referrer: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    timestamp: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "customer_id": "demo_tenant",
                "visitor_id": "visitor_123",
                "user_id": "user_456",
                "session_id": "session_789",
                "event_type": "page_view",
                "event_name": "Pricing Page View",
                "properties": {
                    "page": "/pricing",
                    "title": "Pricing - Our Product"
                },
                "page_url": "https://example.com/pricing",
                "referrer": "https://google.com"
            }
        }


class BatchEventsRequest(BaseModel):
    events: list[Event] = Field(..., description="List of events to ingest")


class IngestionResponse(BaseModel):
    success: bool
    events_accepted: int
    events_rejected: int
    message: str


# Rate limiting
def check_rate_limit(customer_id: str, max_requests: int = 1000, window_seconds: int = 60) -> bool:
    """
    Token bucket rate limiting per customer
    Returns True if request is allowed, False otherwise
    """
    key = f"rate_limit:{customer_id}"
    current_time = int(time.time())
    window_start = current_time - window_seconds

    try:
        # Remove old requests outside the window
        redis_client.zremrangebyscore(key, 0, window_start)

        # Count requests in current window
        request_count = redis_client.zcard(key)

        if request_count >= max_requests:
            return False

        # Add current request
        redis_client.zadd(key, {str(current_time): current_time})
        redis_client.expire(key, window_seconds)

        return True
    except Exception as e:
        logger.error(f"Rate limit check failed: {e}")
        # Fail open - allow request if Redis is down
        return True


def generate_partition_key(customer_id: str, visitor_id: str) -> str:
    """
    Generate Kafka partition key for tenant isolation
    Hash customer_id to ensure same customer goes to same partition
    """
    combined = f"{customer_id}:{visitor_id}"
    return hashlib.md5(combined.encode()).hexdigest()


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "real-time-analytics-ingestion",
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health")
async def health():
    """Detailed health check"""
    health_status = {
        "kafka": "unknown",
        "redis": "unknown"
    }

    # Check Kafka
    try:
        if kafka_producer and kafka_producer.bootstrap_connected():
            health_status["kafka"] = "healthy"
        else:
            health_status["kafka"] = "unhealthy"
    except Exception as e:
        health_status["kafka"] = f"error: {str(e)}"

    # Check Redis
    try:
        redis_client.ping()
        health_status["redis"] = "healthy"
    except Exception as e:
        health_status["redis"] = f"error: {str(e)}"

    is_healthy = all(v == "healthy" for v in health_status.values())
    status_code = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE

    return Response(
        content=json.dumps({
            "status": "healthy" if is_healthy else "degraded",
            "components": health_status,
            "timestamp": datetime.utcnow().isoformat()
        }),
        status_code=status_code,
        media_type="application/json"
    )


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/track", response_model=IngestionResponse)
async def track_event(event: Event, request: Request):
    """
    Ingest a single event
    """
    start_time = time.time()

    # Rate limiting
    if not check_rate_limit(event.customer_id, max_requests=10000, window_seconds=60):
        events_dropped.labels(customer_id=event.customer_id, reason='rate_limit').inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for customer {event.customer_id}"
        )

    # Enrich event with server-side data
    if not event.timestamp:
        event.timestamp = datetime.utcnow()

    if not event.ip_address:
        event.ip_address = request.client.host

    if not event.user_agent:
        event.user_agent = request.headers.get("user-agent")

    # Convert to dict for Kafka
    event_data = event.model_dump()
    event_data['timestamp'] = event.timestamp.isoformat()
    event_data['ingested_at'] = datetime.utcnow().isoformat()

    # Publish to Kafka
    try:
        partition_key = generate_partition_key(event.customer_id, event.visitor_id)

        kafka_producer.send(
            topic='events-raw',
            value=event_data,
            key=partition_key.encode('utf-8')
        )

        # Update metrics
        events_received.labels(customer_id=event.customer_id, event_type=event.event_type).inc()
        events_published.labels(customer_id=event.customer_id).inc()
        ingestion_latency.labels(customer_id=event.customer_id).observe(time.time() - start_time)

        logger.info(
            "Event ingested",
            extra={
                "customer_id": event.customer_id,
                "event_type": event.event_type,
                "visitor_id": event.visitor_id,
                "latency_ms": (time.time() - start_time) * 1000
            }
        )

        return IngestionResponse(
            success=True,
            events_accepted=1,
            events_rejected=0,
            message="Event accepted"
        )

    except Exception as e:
        events_dropped.labels(customer_id=event.customer_id, reason='kafka_error').inc()
        logger.error(f"Failed to publish event to Kafka: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to ingest event"
        )


@app.post("/track/batch", response_model=IngestionResponse)
async def track_batch(batch: BatchEventsRequest, request: Request):
    """
    Ingest multiple events in a batch
    More efficient for SDKs that buffer events
    """
    start_time = time.time()
    events_accepted = 0
    events_rejected = 0

    for event in batch.events:
        try:
            # Rate limiting per customer
            if not check_rate_limit(event.customer_id, max_requests=10000, window_seconds=60):
                events_rejected += 1
                events_dropped.labels(customer_id=event.customer_id, reason='rate_limit').inc()
                continue

            # Enrich event
            if not event.timestamp:
                event.timestamp = datetime.utcnow()
            if not event.ip_address:
                event.ip_address = request.client.host
            if not event.user_agent:
                event.user_agent = request.headers.get("user-agent")

            # Convert to dict
            event_data = event.model_dump()
            event_data['timestamp'] = event.timestamp.isoformat()
            event_data['ingested_at'] = datetime.utcnow().isoformat()

            # Publish to Kafka
            partition_key = generate_partition_key(event.customer_id, event.visitor_id)
            kafka_producer.send(
                topic='events-raw',
                value=event_data,
                key=partition_key.encode('utf-8')
            )

            events_received.labels(customer_id=event.customer_id, event_type=event.event_type).inc()
            events_published.labels(customer_id=event.customer_id).inc()
            events_accepted += 1

        except Exception as e:
            events_rejected += 1
            events_dropped.labels(customer_id=event.customer_id, reason='kafka_error').inc()
            logger.error(f"Failed to process event in batch: {e}")

    # Record latency
    for event in batch.events:
        ingestion_latency.labels(customer_id=event.customer_id).observe(time.time() - start_time)

    logger.info(
        "Batch processed",
        extra={
            "events_accepted": events_accepted,
            "events_rejected": events_rejected,
            "latency_ms": (time.time() - start_time) * 1000
        }
    )

    return IngestionResponse(
        success=events_rejected == 0,
        events_accepted=events_accepted,
        events_rejected=events_rejected,
        message=f"Processed {events_accepted} events, rejected {events_rejected}"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
