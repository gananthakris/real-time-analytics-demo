# API Documentation

## Ingestion API (Port 8000)

### Health Check

```bash
GET /

Response:
{
  "service": "real-time-analytics-ingestion",
  "status": "healthy",
  "timestamp": "2026-02-16T12:00:00.000Z"
}
```

### Track Single Event

```bash
POST /track
Content-Type: application/json

{
  "customer_id": "demo_tenant",
  "visitor_id": "visitor_123",
  "user_id": "user_456",
  "session_id": "session_789",
  "event_type": "page_view",
  "event_name": "Homepage View",
  "properties": {
    "page": "/",
    "title": "Home"
  },
  "page_url": "https://example.com/",
  "referrer": "https://google.com"
}

Response:
{
  "success": true,
  "events_accepted": 1,
  "events_rejected": 0,
  "message": "Event accepted"
}
```

### Track Batch of Events

```bash
POST /track/batch
Content-Type: application/json

{
  "events": [
    {
      "customer_id": "demo_tenant",
      "visitor_id": "visitor_123",
      "session_id": "session_789",
      "event_type": "page_view",
      "event_name": "Homepage View",
      "properties": {}
    },
    {
      "customer_id": "demo_tenant",
      "visitor_id": "visitor_123",
      "session_id": "session_789",
      "event_type": "button_click",
      "event_name": "CTA Click",
      "properties": {
        "button_id": "signup_cta"
      }
    }
  ]
}

Response:
{
  "success": true,
  "events_accepted": 2,
  "events_rejected": 0,
  "message": "Processed 2 events, rejected 0"
}
```

### Metrics (Prometheus)

```bash
GET /metrics

Response:
# TYPE events_received_total counter
events_received_total{customer_id="demo_tenant",event_type="page_view"} 1234

# TYPE ingestion_latency_seconds histogram
ingestion_latency_seconds_bucket{customer_id="demo_tenant",le="0.005"} 100
...
```

---

## Analytics API (Port 8001)

### Health Check

```bash
GET /

Response:
{
  "service": "real-time-analytics-api",
  "status": "healthy",
  "ai_enabled": true,
  "timestamp": "2026-02-16T12:00:00.000Z"
}
```

### Direct SQL Query

```bash
POST /query
Content-Type: application/json

{
  "customer_id": "demo_tenant",
  "sql": "SELECT count(*) as total FROM events_raw WHERE customer_id = 'demo_tenant'"
}

Response:
{
  "success": true,
  "data": [
    {"total": 1234}
  ],
  "columns": ["total"],
  "row_count": 1,
  "execution_time_ms": 45.2
}
```

### AI-Powered Natural Language Query ⭐

```bash
POST /ai/query
Content-Type: application/json

{
  "customer_id": "demo_tenant",
  "query": "Show me the top 10 pages by views today",
  "execute": true
}

Response:
{
  "success": true,
  "sql": "SELECT JSONExtractString(properties, 'page') AS page, count() AS views, uniq(visitor_id) AS unique_visitors FROM events_raw WHERE customer_id = 'demo_tenant' AND event_type = 'page_view' AND toDate(timestamp) = today() GROUP BY page ORDER BY views DESC LIMIT 10",
  "explanation": "This query finds the top 10 most viewed pages for today, showing both total views and unique visitors for each page.",
  "insights": "The homepage (/) has the most views with 456 total views from 234 unique visitors. The pricing page comes second with 123 views from 89 unique visitors, indicating strong interest in your product. Consider A/B testing the pricing page to improve conversion.",
  "related_queries": [
    "What is the average time spent on the top pages?",
    "Show me conversion rate from pricing page to signup",
    "Compare today's traffic to yesterday"
  ],
  "data": [
    {
      "page": "/",
      "views": 456,
      "unique_visitors": 234
    },
    {
      "page": "/pricing",
      "views": 123,
      "unique_visitors": 89
    }
  ],
  "execution_time_ms": 1245.6
}
```

**Example Queries to Try:**

1. "Find users who abandoned cart after viewing pricing 3+ times"
2. "What are the most common events in the last hour?"
3. "Show me conversion funnel for signup process"
4. "Compare page views today vs yesterday"
5. "Which pages have the highest bounce rate?"

### Real-Time Dashboard

```bash
GET /dashboard/realtime/{customer_id}

Response:
{
  "customer_id": "demo_tenant",
  "timestamp": "2026-02-16T12:00:00.000Z",
  "events_timeline": [
    {
      "minute": "2026-02-16T11:59:00.000Z",
      "event_count": 45,
      "unique_visitors": 23
    },
    ...
  ],
  "top_events": [
    {
      "event_type": "page_view",
      "count": 234
    },
    ...
  ],
  "top_pages": [
    {
      "page": "/",
      "views": 123,
      "unique_visitors": 67
    },
    ...
  ]
}
```

### Event Stream (Server-Sent Events)

```bash
GET /events/stream/{customer_id}

Response (SSE stream):
event: new_events
data: [{"event_type":"page_view","event_name":"Homepage View","visitor_id":"visitor_123","timestamp":"2026-02-16T12:00:00.000Z"}]

event: new_events
data: [{"event_type":"button_click","event_name":"CTA Click","visitor_id":"visitor_456","timestamp":"2026-02-16T12:00:05.000Z"}]
```

**JavaScript Example:**

```javascript
const eventSource = new EventSource('http://localhost:8001/events/stream/demo_tenant');

eventSource.addEventListener('new_events', (e) => {
  const events = JSON.parse(e.data);
  console.log('New events:', events);
});
```

---

## JavaScript SDK

### Installation

**Via Script Tag:**

```html
<script src="tracker.js"></script>
<script>
  const analytics = new AnalyticsTracker({
    apiUrl: 'http://localhost:8000',
    customerId: 'demo_tenant',
    debug: true
  });
</script>
```

**Via Module:**

```javascript
import AnalyticsTracker from './tracker.js';

const analytics = new AnalyticsTracker({
  apiUrl: 'http://localhost:8000',
  customerId: 'demo_tenant',
  batchSize: 10,
  flushInterval: 5000,
  autoTrackPageViews: true
});
```

### Usage

**Track Page View:**

```javascript
analytics.page({
  page: '/pricing',
  title: 'Pricing Page'
});
```

**Track Custom Event:**

```javascript
analytics.track('button_click', 'CTA Click', {
  button_id: 'signup_cta',
  position: 'header'
});
```

**Track Form Submission:**

```javascript
analytics.formSubmit('contact_form', {
  fields: ['name', 'email', 'message']
});
```

**Identify User (After Login):**

```javascript
analytics.identify('user_123', {
  email: 'user@example.com',
  plan: 'pro'
});
```

**Manual Flush:**

```javascript
analytics.flush();
```

---

## ClickHouse Direct Queries

### Connect

```bash
# CLI
docker-compose exec clickhouse clickhouse-client

# HTTP
curl 'http://localhost:8123/?query=SELECT+1'
```

### Useful Queries

**Total Events:**

```sql
SELECT
  count() as total_events,
  uniq(visitor_id) as unique_visitors,
  uniq(user_id) as identified_users
FROM events_raw
WHERE customer_id = 'demo_tenant';
```

**Events Over Time:**

```sql
SELECT
  toStartOfHour(timestamp) as hour,
  count() as event_count,
  uniq(visitor_id) as unique_visitors
FROM events_raw
WHERE customer_id = 'demo_tenant'
  AND timestamp >= now() - INTERVAL 24 HOUR
GROUP BY hour
ORDER BY hour DESC;
```

**Top Events:**

```sql
SELECT
  event_type,
  count() as count,
  uniq(visitor_id) as unique_visitors
FROM events_raw
WHERE customer_id = 'demo_tenant'
GROUP BY event_type
ORDER BY count DESC
LIMIT 10;
```

**User Journey:**

```sql
SELECT
  timestamp,
  event_type,
  event_name,
  properties
FROM events_raw
WHERE customer_id = 'demo_tenant'
  AND visitor_id = 'visitor_123'
ORDER BY timestamp DESC
LIMIT 100;
```

**Cart Abandonment Analysis:**

```sql
SELECT
  visitor_id,
  count(*) as pricing_views,
  max(timestamp) as last_pricing_view,
  any(timestamp) as cart_abandon_time
FROM events_raw
WHERE customer_id = 'demo_tenant'
  AND event_type = 'page_view'
  AND JSONExtractString(properties, 'page') LIKE '%pricing%'
  AND visitor_id IN (
    SELECT visitor_id FROM events_raw
    WHERE customer_id = 'demo_tenant'
      AND event_type = 'cart_abandon'
  )
GROUP BY visitor_id
HAVING pricing_views >= 3
ORDER BY pricing_views DESC;
```

---

## Rate Limits

### Ingestion API

- **Per Customer:** 10,000 events/minute (default)
- **Enterprise Tier:** 100,000 events/minute
- **Response:** HTTP 429 when limit exceeded

### Analytics API

- **SQL Queries:** 100/minute per customer
- **AI Queries:** 100/hour per customer (cache bypasses limit)
- **Response:** HTTP 429 when limit exceeded

---

## Error Codes

### Ingestion API

| Code | Message | Resolution |
|------|---------|------------|
| 400 | Invalid event format | Check JSON schema |
| 429 | Rate limit exceeded | Wait or upgrade plan |
| 500 | Kafka unavailable | Retry with backoff |
| 503 | Service degraded | Check /health endpoint |

### Analytics API

| Code | Message | Resolution |
|------|---------|------------|
| 400 | Invalid SQL query | Check syntax |
| 403 | Missing customer_id filter | Add WHERE customer_id = '...' |
| 429 | Rate limit exceeded | Wait or use cache |
| 503 | AI features unavailable | Set ANTHROPIC_API_KEY |

---

## Monitoring

### Prometheus Metrics

**Available at:** http://localhost:9090

**Key Metrics:**
- `events_received_total`
- `events_dropped_total`
- `ingestion_latency_seconds`
- `analytics_queries_total`
- `ai_queries_total`
- `query_latency_seconds`

### Grafana Dashboards

**Available at:** http://localhost:3000 (admin/admin)

**Pre-built Dashboards:**
1. Ingestion Overview
2. Query Performance
3. System Health
4. Per-Customer Metrics

---

## Authentication (Production)

**Local Development:** No authentication required

**Production:** Add API key authentication

```bash
POST /track
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json
```

**Configure:**

```python
# In production, add authentication middleware
app.add_middleware(
    AuthenticationMiddleware,
    backend=APIKeyAuthBackend()
)
```

---

## Support

For issues or questions:
1. Check logs: `docker-compose logs -f [service]`
2. Check metrics: http://localhost:9090
3. Verify ClickHouse: `docker-compose exec clickhouse clickhouse-client`
4. Run health checks: `curl http://localhost:8000/health`
