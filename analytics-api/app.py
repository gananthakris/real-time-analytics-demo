"""
Analytics API with GraphQL and AI-Powered Natural Language Queries
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field
from clickhouse_driver import Client
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import redis
from sse_starlette.sse import EventSourceResponse

from ai_analytics import AIAnalyticsEngine, MockAIAnalyticsEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prometheus metrics
queries_total = Counter('analytics_queries_total', 'Total analytics queries', ['customer_id', 'query_type'])
query_latency = Histogram('analytics_query_latency_seconds', 'Query latency', ['customer_id'])
ai_queries_total = Counter('ai_queries_total', 'Total AI queries', ['customer_id'])

# Global connections
clickhouse_client = None
redis_client = None
ai_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown"""
    global clickhouse_client, redis_client, ai_engine

    # Startup
    logger.info("Starting analytics API...")

    clickhouse_client = Client(
        host='localhost',
        port=9000,
        database='analytics',
        user='admin',
        password='password'
    )
    logger.info("ClickHouse client initialized")

    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    logger.info("Redis client initialized")

    # Initialize AI engine
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_api_key:
        ai_engine = AIAnalyticsEngine(anthropic_api_key=anthropic_api_key, redis_host='localhost')
        logger.info("AI analytics engine initialized")
    else:
        ai_engine = MockAIAnalyticsEngine(redis_host='localhost')
        logger.info("AI analytics engine initialized (template mode — no API key)")

    yield

    # Shutdown
    logger.info("Shutting down analytics API...")
    if clickhouse_client:
        clickhouse_client.disconnect()
    if redis_client:
        redis_client.close()


app = FastAPI(
    title="Real-Time Analytics API",
    description="Analytics API with AI-powered natural language queries",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models
class QueryRequest(BaseModel):
    sql: str = Field(..., description="ClickHouse SQL query")
    customer_id: str = Field(..., description="Customer ID for tenant isolation")


class NaturalLanguageQueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
    customer_id: str = Field(..., description="Customer ID")
    execute: bool = Field(True, description="Execute the generated SQL immediately")


class QueryResponse(BaseModel):
    success: bool
    data: Optional[List[Dict[str, Any]]] = None
    columns: Optional[List[str]] = None
    row_count: int = 0
    execution_time_ms: float = 0
    error: Optional[str] = None


class AIQueryResponse(BaseModel):
    success: bool
    sql: Optional[str] = None
    explanation: Optional[str] = None
    insights: Optional[str] = None
    related_queries: List[str] = []
    data: Optional[List[Dict[str, Any]]] = None
    execution_time_ms: float = 0
    error: Optional[str] = None


# Utility functions
def execute_clickhouse_query(sql: str, customer_id: str) -> Dict[str, Any]:
    """Execute ClickHouse query and return results"""
    import time
    start_time = time.time()

    try:
        # Security check: ensure customer_id filter exists
        if f"customer_id = '{customer_id}'" not in sql:
            raise ValueError("Query must include customer_id filter")

        # Execute query
        result = clickhouse_client.execute(sql, with_column_types=True)

        # Parse results
        rows = result[0]
        columns_with_types = result[1]
        column_names = [col[0] for col in columns_with_types]

        # Convert to list of dicts
        data = []
        for row in rows:
            row_dict = {}
            for i, value in enumerate(row):
                # Convert datetime objects to ISO strings
                if isinstance(value, datetime):
                    value = value.isoformat()
                row_dict[column_names[i]] = value
            data.append(row_dict)

        execution_time = (time.time() - start_time) * 1000

        return {
            "success": True,
            "data": data,
            "columns": column_names,
            "row_count": len(data),
            "execution_time_ms": execution_time
        }

    except Exception as e:
        logger.error(f"Query execution error: {e}")
        return {
            "success": False,
            "error": str(e),
            "execution_time_ms": (time.time() - start_time) * 1000
        }


# Endpoints
@app.get("/")
async def root():
    """Health check"""
    return {
        "service": "real-time-analytics-api",
        "status": "healthy",
        "ai_enabled": ai_engine is not None,
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/query", response_model=QueryResponse)
async def execute_query(request: QueryRequest):
    """
    Execute a direct SQL query
    """
    queries_total.labels(customer_id=request.customer_id, query_type='sql').inc()

    result = execute_clickhouse_query(request.sql, request.customer_id)

    query_latency.labels(customer_id=request.customer_id).observe(
        result.get('execution_time_ms', 0) / 1000
    )

    return QueryResponse(**result)


@app.post("/ai/query", response_model=AIQueryResponse)
async def ai_query(request: NaturalLanguageQueryRequest):
    """
    AI-powered natural language query
    THIS IS THE KEY DIFFERENTIATOR!
    """
    if not ai_engine:
        raise HTTPException(status_code=503, detail="AI features not available - ANTHROPIC_API_KEY not set")

    ai_queries_total.labels(customer_id=request.customer_id).inc()
    import time
    start_time = time.time()

    try:
        # Generate SQL from natural language
        ai_result = ai_engine.generate_sql(request.query, request.customer_id)

        if ai_result.get('error'):
            return AIQueryResponse(
                success=False,
                error=ai_result['error'],
                execution_time_ms=(time.time() - start_time) * 1000
            )

        response = AIQueryResponse(
            success=True,
            sql=ai_result.get('sql'),
            explanation=ai_result.get('explanation'),
            insights=ai_result.get('insights'),
            related_queries=ai_result.get('related_queries', []),
            execution_time_ms=0
        )

        # Execute the query if requested
        if request.execute and ai_result.get('sql'):
            query_result = execute_clickhouse_query(ai_result['sql'], request.customer_id)

            if query_result.get('success'):
                response.data = query_result['data']

                # Generate insights from results
                if query_result['data']:
                    insights = ai_engine.explain_insights(
                        query_result['data'],
                        request.query
                    )
                    response.insights = insights
            else:
                response.error = query_result.get('error')
                response.success = False

        response.execution_time_ms = (time.time() - start_time) * 1000
        return response

    except Exception as e:
        logger.error(f"AI query error: {e}")
        return AIQueryResponse(
            success=False,
            error=str(e),
            execution_time_ms=(time.time() - start_time) * 1000
        )


@app.get("/dashboard/realtime/{customer_id}")
async def realtime_dashboard(customer_id: str):
    """
    Get real-time dashboard metrics
    """
    try:
        # Events in last hour
        events_query = f"""
        SELECT
            toStartOfMinute(timestamp) AS minute,
            count() AS event_count,
            uniq(visitor_id) AS unique_visitors
        FROM events_raw
        WHERE customer_id = '{customer_id}'
          AND timestamp >= now() - INTERVAL 1 HOUR
        GROUP BY minute
        ORDER BY minute DESC
        LIMIT 60
        """

        events_result = execute_clickhouse_query(events_query, customer_id)

        # Top events
        top_events_query = f"""
        SELECT
            event_type,
            count() AS count
        FROM events_raw
        WHERE customer_id = '{customer_id}'
          AND timestamp >= now() - INTERVAL 1 HOUR
        GROUP BY event_type
        ORDER BY count DESC
        LIMIT 10
        """

        top_events_result = execute_clickhouse_query(top_events_query, customer_id)

        # Top pages
        top_pages_query = f"""
        SELECT
            JSONExtractString(properties, 'page') AS page,
            count() AS views,
            uniq(visitor_id) AS unique_visitors
        FROM events_raw
        WHERE customer_id = '{customer_id}'
          AND event_type = 'page_view'
          AND timestamp >= now() - INTERVAL 1 HOUR
        GROUP BY page
        ORDER BY views DESC
        LIMIT 10
        """

        top_pages_result = execute_clickhouse_query(top_pages_query, customer_id)

        return {
            "customer_id": customer_id,
            "timestamp": datetime.utcnow().isoformat(),
            "events_timeline": events_result.get('data', []),
            "top_events": top_events_result.get('data', []),
            "top_pages": top_pages_result.get('data', [])
        }

    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/events/stream/{customer_id}")
async def event_stream(customer_id: str, request: Request):
    """
    Server-Sent Events stream for real-time updates
    """
    async def event_generator():
        last_timestamp = datetime.utcnow()

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            try:
                # Query for new events since last check
                query = f"""
                SELECT
                    event_type,
                    event_name,
                    visitor_id,
                    timestamp
                FROM events_raw
                WHERE customer_id = '{customer_id}'
                  AND timestamp > '{last_timestamp.isoformat()}'
                ORDER BY timestamp DESC
                LIMIT 100
                """

                result = clickhouse_client.execute(query)

                if result:
                    events = []
                    for row in result:
                        events.append({
                            "event_type": row[0],
                            "event_name": row[1],
                            "visitor_id": row[2],
                            "timestamp": row[3].isoformat() if isinstance(row[3], datetime) else row[3]
                        })
                        last_timestamp = max(last_timestamp, row[3] if isinstance(row[3], datetime) else datetime.fromisoformat(row[3]))

                    if events:
                        yield {
                            "event": "new_events",
                            "data": json.dumps(events)
                        }

                # Sleep for 2 seconds before next check
                import asyncio
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Event stream error: {e}")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": str(e)})
                }

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
