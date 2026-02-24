-- ClickHouse Schema for Real-Time Analytics Pipeline
-- Multi-tenant design with partition-based isolation

-- Main events table (raw events)
CREATE TABLE IF NOT EXISTS events_raw (
    customer_id String,
    visitor_id String,
    user_id Nullable(String),
    session_id String,
    event_type String,
    event_name String,
    properties String,  -- JSON string
    page_url Nullable(String),
    referrer Nullable(String),
    user_agent Nullable(String),
    ip_address Nullable(String),
    timestamp DateTime64(3),
    ingested_at DateTime64(3) DEFAULT now64()
)
ENGINE = MergeTree()
PARTITION BY (customer_id, toYYYYMM(timestamp))
ORDER BY (customer_id, timestamp, event_type, visitor_id)
TTL toDateTime(timestamp) + INTERVAL 90 DAY DELETE
SETTINGS index_granularity = 8192;

-- Hourly aggregation materialized view
CREATE TABLE IF NOT EXISTS events_hourly (
    customer_id String,
    event_type String,
    hour DateTime,
    event_count UInt64,
    unique_visitors AggregateFunction(uniq, String),
    unique_users AggregateFunction(uniq, Nullable(String))
)
ENGINE = AggregatingMergeTree()
PARTITION BY (customer_id, toYYYYMM(hour))
ORDER BY (customer_id, event_type, hour)
TTL hour + INTERVAL 30 DAY DELETE;

-- Materialized view to populate hourly aggregations
CREATE MATERIALIZED VIEW IF NOT EXISTS events_hourly_mv
TO events_hourly
AS SELECT
    customer_id,
    event_type,
    toStartOfHour(timestamp) AS hour,
    count() AS event_count,
    uniqState(visitor_id) AS unique_visitors,
    uniqState(user_id) AS unique_users
FROM events_raw
GROUP BY customer_id, event_type, hour;

-- User sessions table
CREATE TABLE IF NOT EXISTS user_sessions (
    customer_id String,
    session_id String,
    visitor_id String,
    user_id Nullable(String),
    session_start DateTime64(3),
    session_end DateTime64(3),
    page_views UInt32,
    events_count UInt32,
    duration_seconds UInt32,
    landing_page String,
    exit_page String,
    referrer Nullable(String),
    device_type Nullable(String),
    browser Nullable(String),
    country Nullable(String)
)
ENGINE = ReplacingMergeTree(session_end)
PARTITION BY (customer_id, toYYYYMM(session_start))
ORDER BY (customer_id, session_id, visitor_id)
TTL toDateTime(session_start) + INTERVAL 90 DAY DELETE;

-- User profiles table (identity stitching)
CREATE TABLE IF NOT EXISTS user_profiles (
    customer_id String,
    user_id String,
    visitor_ids Array(String),
    email Nullable(String),
    first_seen DateTime64(3),
    last_seen DateTime64(3),
    total_sessions UInt32,
    total_events UInt32,
    properties String,  -- JSON string for custom attributes
    created_at DateTime64(3) DEFAULT now64(),
    updated_at DateTime64(3) DEFAULT now64()
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY (customer_id)
ORDER BY (customer_id, user_id)
TTL toDateTime(created_at) + INTERVAL 365 DAY DELETE;

-- Page analytics table
CREATE TABLE IF NOT EXISTS page_analytics (
    customer_id String,
    page_url String,
    date Date,
    page_views UInt64,
    unique_visitors AggregateFunction(uniq, String),
    avg_time_on_page AggregateFunction(avg, Float64),
    bounce_rate Float32
)
ENGINE = AggregatingMergeTree()
PARTITION BY (customer_id, toYYYYMM(date))
ORDER BY (customer_id, date, page_url)
TTL date + INTERVAL 90 DAY DELETE;

-- Conversion funnels table
CREATE TABLE IF NOT EXISTS conversion_funnels (
    customer_id String,
    funnel_name String,
    visitor_id String,
    step_number UInt8,
    step_name String,
    timestamp DateTime64(3),
    completed Boolean
)
ENGINE = MergeTree()
PARTITION BY (customer_id, toYYYYMM(timestamp))
ORDER BY (customer_id, funnel_name, visitor_id, step_number, timestamp)
TTL toDateTime(timestamp) + INTERVAL 90 DAY DELETE;

-- User segments table
CREATE TABLE IF NOT EXISTS user_segments (
    customer_id String,
    segment_name String,
    visitor_id String,
    user_id Nullable(String),
    entered_at DateTime64(3),
    exited_at Nullable(DateTime64(3)),
    is_active Boolean DEFAULT true
)
ENGINE = ReplacingMergeTree(entered_at)
PARTITION BY (customer_id, segment_name)
ORDER BY (customer_id, segment_name, visitor_id)
TTL toDateTime(entered_at) + INTERVAL 90 DAY DELETE;

-- Real-time dashboard metrics (last 24 hours, high performance)
CREATE TABLE IF NOT EXISTS realtime_metrics (
    customer_id String,
    metric_name String,
    metric_value Float64,
    dimensions String,  -- JSON string
    timestamp DateTime64(3)
)
ENGINE = MergeTree()
PARTITION BY (customer_id, toDate(timestamp))
ORDER BY (customer_id, metric_name, timestamp)
TTL toDateTime(timestamp) + INTERVAL 7 DAY DELETE;

-- Create indexes for common queries
-- Bloom filter for visitor_id lookups
ALTER TABLE events_raw ADD INDEX visitor_id_idx visitor_id TYPE bloom_filter GRANULARITY 4;
ALTER TABLE events_raw ADD INDEX event_type_idx event_type TYPE bloom_filter GRANULARITY 4;

-- Sample queries for verification

-- Query 1: Events per second (last hour)
-- SELECT
--     toStartOfMinute(timestamp) AS minute,
--     count() / 60 AS events_per_second
-- FROM events_raw
-- WHERE customer_id = 'demo_tenant'
--   AND timestamp >= now() - INTERVAL 1 HOUR
-- GROUP BY minute
-- ORDER BY minute DESC;

-- Query 2: Top pages by views (today)
-- SELECT
--     JSONExtractString(properties, 'page') AS page,
--     count() AS views,
--     uniq(visitor_id) AS unique_visitors
-- FROM events_raw
-- WHERE customer_id = 'demo_tenant'
--   AND event_type = 'page_view'
--   AND toDate(timestamp) = today()
-- GROUP BY page
-- ORDER BY views DESC
-- LIMIT 10;

-- Query 3: User journey (specific visitor)
-- SELECT
--     timestamp,
--     event_type,
--     event_name,
--     properties
-- FROM events_raw
-- WHERE customer_id = 'demo_tenant'
--   AND visitor_id = 'visitor_123'
-- ORDER BY timestamp DESC
-- LIMIT 100;

-- Query 4: Conversion funnel analysis
-- SELECT
--     step_name,
--     count(DISTINCT visitor_id) AS users,
--     countIf(completed = true) AS completed_count,
--     (completed_count / users) * 100 AS completion_rate
-- FROM conversion_funnels
-- WHERE customer_id = 'demo_tenant'
--   AND funnel_name = 'signup_funnel'
--   AND timestamp >= now() - INTERVAL 7 DAY
-- GROUP BY step_name, step_number
-- ORDER BY step_number;

-- Insert sample data for testing
INSERT INTO events_raw (customer_id, visitor_id, user_id, session_id, event_type, event_name, properties, page_url, timestamp)
VALUES
    ('demo_tenant', 'visitor_001', NULL, 'session_001', 'page_view', 'Home Page View', '{"page": "/", "title": "Home"}', '/', now() - INTERVAL 5 MINUTE),
    ('demo_tenant', 'visitor_001', NULL, 'session_001', 'page_view', 'Pricing Page View', '{"page": "/pricing", "title": "Pricing"}', '/pricing', now() - INTERVAL 4 MINUTE),
    ('demo_tenant', 'visitor_001', NULL, 'session_001', 'page_view', 'Pricing Page View', '{"page": "/pricing", "title": "Pricing"}', '/pricing', now() - INTERVAL 3 MINUTE),
    ('demo_tenant', 'visitor_001', NULL, 'session_001', 'cart_add', 'Added to Cart', '{"product_id": "pro_plan", "price": 99}', '/pricing', now() - INTERVAL 2 MINUTE),
    ('demo_tenant', 'visitor_001', NULL, 'session_001', 'cart_abandon', 'Cart Abandoned', '{"cart_value": 99}', '/checkout', now() - INTERVAL 1 MINUTE),
    ('demo_tenant', 'visitor_002', 'user_001', 'session_002', 'page_view', 'Dashboard View', '{"page": "/dashboard"}', '/dashboard', now() - INTERVAL 10 MINUTE),
    ('demo_tenant', 'visitor_002', 'user_001', 'session_002', 'button_click', 'Export Data', '{"button_id": "export_csv"}', '/dashboard', now() - INTERVAL 8 MINUTE),
    ('acme_corp', 'visitor_003', NULL, 'session_003', 'page_view', 'Landing Page', '{"page": "/", "utm_source": "google"}', '/', now() - INTERVAL 15 MINUTE),
    ('acme_corp', 'visitor_003', NULL, 'session_003', 'form_submit', 'Contact Form', '{"form_id": "contact", "email": "test@acme.com"}', '/contact', now() - INTERVAL 12 MINUTE);
