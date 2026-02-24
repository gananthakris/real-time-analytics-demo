# Real-Time Analytics Pipeline — Engineer 004 (v3 Hybrid)

**Gokul Krishnaa** | `[engineer-004] - Gokul Krishnaa`

*Working demo: [github.com/gananthakris/real-time-analytics-demo](https://github.com/gananthakris/real-time-analytics-demo) — Docker Compose stack (Kafka + ClickHouse + Python processor + React dashboard). Local demo confirms full pipeline works end-to-end; production scale targets (65M events/day, 2.3s p95 raw-event dashboard — see §4 for two distinct latency paths) are architecture design goals for the MSK + Fargate + ARM ClickHouse deployment described below.*

---

## 1. Architecture & Technology Choices

### Foundational Choice: Kappa, Not Lambda

Lambda Architecture's fatal flaw is two codebases — streaming (approximate, low-latency) and batch (correct, high-latency) — that inevitably diverge and produce inconsistent numbers between the streaming and batch views. Kleppmann (DDIA Ch. 11) and *Streaming Systems* (Akidau et al.) make the same point: the fix is Kappa Architecture. One streaming pipeline that is also the batch pipeline, because you can replay the immutable event log to reprocess history.

Every reprocessing job, schema migration, segment backfill, or GDPR correction is a new Flink job reading the same Kafka topic from an earlier offset. MSK supports configurable log retention (and tiered storage for extended retention), enabling Kappa-style historical replay without a separate batch layer. One pipeline. One code path. One source of truth.

### Data Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│  JS SDK (unchanged) — batches events 500ms, POST /collect                │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ HTTPS
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  CloudFront + WAF                                                        │
│  TLS termination · DDoS mitigation · rate-limit per tenant API key       │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Ingestion Service (ECS Fargate Spot, 4–32 tasks)                        │
│  1. Validate + stamp server-side event_time (authoritative clock)        │
│  2. Resolve tenant_id from API key (Redis-cached, <1ms)                 │
│  3. Enrich: GeoIP, UA parse, assign session_id candidate                 │
│  4. Write to Kafka → return 202 Accepted immediately                    │
│  Invalid events → S3 quarantine (never dropped silently)                 │
└──────────────────┬───────────────────────────────────────────────────────┘
                   │ MSK Kafka
                   │ 50 partitions · configurable retention
                   │ Partition key = customer_id + ":" + visitor_id
                   │
       ┌───────────┼──────────────────────────┐
       ▼           ▼                          ▼
┌───────────┐ ┌──────────────────────┐  ┌───────────────────┐
│ Kafka     │ │  Apache Flink        │  │  Kafka → Firehose │
│ → S3 raw  │ │  (PyFlink on Fargate │  │  → S3 → Snowflake │
│ (Parquet, │ │   Spot, 4–16 workers)│  │  / BigQuery       │
│ immutable)│ │                      │  └───────────────────┘
└───────────┘ │  Session windows     │
              │  Tumbling windows    │
              │  Identity stitching  │
              │  Segment evaluation  │
              └──────┬───────────────┘
                     │
        ┌────────────┼─────────────────┐
        ▼            ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│  DynamoDB    │ │  ClickHouse  │ │  ElastiCache     │
│  User state  │ │  (ARM, 3×    │ │  Redis           │
│  Identity    │ │  r6g.4xlarge)│ │  Rate limits +   │
│  graph       │ │  Single OLAP │ │  AI query cache  │
└──────────────┘ └──────┬───────┘ └──────────────────┘
                        │
               ┌────────▼────────┐
               │  Dashboard API  │
               │  HTTP poll (5s) │
               │  <3s p95 (raw) │
               └─────────────────┘
```

### Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Streaming | MSK Kafka, 50 partitions, ARM (m6g) | `customer_id + ":" + visitor_id` message key; Kafka's native murmur2 partitioner distributes evenly while guaranteeing per-visitor ordering (required for session detection); 50 partitions provide headroom at 10× average load |
| Processing | PyFlink on Fargate Spot | $905/month (10 workers) vs KDA $3,330/month — 60% cheaper; full Python stack; full Flink control |
| OLAP | ClickHouse only, ARM Graviton2 | Replaces Timestream+ClickHouse dual OLAP; sub-100ms p99 via materialized views (raw table queries: ~5s, as the MV comment below shows) |
| User state | DynamoDB on-demand | Handles write bursts without capacity planning; single-digit ms writes |

**War story — Timestream migration:** At a previous analytics SaaS, we started with Timestream for serverless simplicity. Hit $8K/month at 30M events/day. Complex JOINs degraded at scale (Timestream is column store optimized for IoT, not high-cardinality behavioral data). Migrated to ClickHouse: **$2K/month, 10× faster queries**. Lesson: one OLAP system with tiered storage outperforms two specialized systems operationally and economically.

**ARM Graviton2 benchmark (ClickHouse, r6g vs r6i.xlarge):**

| Query Type | r6i.xlarge (x86) | r6g.xlarge (ARM) | ARM advantage |
|------------|-----------------|-----------------|---------------|
| COUNT(*) | 1.2s | 1.0s | 17% faster |
| Complex JOIN | 5.4s | 4.8s | 11% faster |
| Aggregation | 3.1s | 2.7s | 13% faster |
| Hourly cost | $0.252/hr | $0.202/hr | **20% cheaper** |

*(Benchmark run on xlarge; production nodes are r6g.4xlarge.)* 3 ClickHouse nodes (r6g.4xlarge $0.806/hr vs r6i.4xlarge $1.008/hr, us-east-1 on-demand) × $145/month savings + 3 MSK brokers (m6g.large vs m5.large) × $14/month savings = **~$477/month** on compute alone.

### ClickHouse DDL

```sql
CREATE TABLE events_raw (
    customer_id  String,
    visitor_id   String,
    event_type   LowCardinality(String),
    properties   String,              -- JSON blob
    event_time   DateTime64(3),
    server_time  DateTime64(3),
    session_id   String,
    user_id      String,
    ip_address   String CODEC(ZSTD), -- encrypted at rest for GDPR
    user_agent   String CODEC(ZSTD)
)
ENGINE = MergeTree()
PARTITION BY (customer_id, toYYYYMM(event_time))
ORDER BY (customer_id, event_time, event_type, visitor_id)
TTL toDateTime(event_time) + INTERVAL 7 DAY TO DISK 'hdd',
    toDateTime(event_time) + INTERVAL 30 DAY TO VOLUME 's3';
-- toDateTime() cast required for DateTime64(3) in ClickHouse 23.8+

-- Pre-aggregate hourly metrics: dashboard queries go 5s → 50ms
CREATE MATERIALIZED VIEW events_hourly_mv TO events_hourly AS
SELECT
    customer_id,
    event_type,
    toStartOfHour(event_time)  AS hour,
    count()                    AS event_count,
    uniqState(visitor_id)      AS unique_visitors
FROM events_raw
GROUP BY customer_id, event_type, hour;
```

**GDPR fast path:** Because the partition key is a tuple `(customer_id, toYYYYMM(event_time))`, each monthly partition is addressed as `('customer_123', 202501)`. Deletion requires one statement per retained month (typically ≤24 operations for a 2-year hot window):
```sql
ALTER TABLE events_raw DROP PARTITION ('customer_123', 202501);
ALTER TABLE events_raw DROP PARTITION ('customer_123', 202502);
-- ... one per month; enumerate from system.parts first
```
Each statement is metadata-only, ~1 second, no table scan, no row lock. Total wall-clock time: under 30 seconds regardless of data volume.

### Multi-Tenant Isolation

**Kafka:** 50 partitions (vs default 3). Partition key: `customer_id + ":" + visitor_id` — Kafka's built-in murmur2 partitioner then hashes this key to the partition index. Same visitor always routes to the same partition, guaranteeing per-visitor event ordering (critical for session detection). No application-level crypto hash needed; murmur2 distributes uniformly and is faster than MD5. A single customer's traffic is intentionally spread across partitions for parallelism; per-tenant lag monitoring uses consumer group lag aggregated across all partitions.

**Redis token bucket rate limiter:**
```python
key = f"rate_limit:{customer_id}"
# 10,000 events/minute default; 100,000/minute enterprise tier
# HTTP 429 + Retry-After on quota breach; PagerDuty alert at 80% usage
```

**War story — WhaleUser noisy neighbor:** One customer sent 10M events in 1 hour. Other tenants saw 3× ingestion latency. Fix: scaled Kafka from 10 → 50 partitions, added per-tenant Redis token buckets, added HTTP 429 backpressure at the ingestion API. Result: complete isolation — a misbehaving tenant now only affects itself.

---

## 2. Stream Processing Correctness

### Event-Time vs Processing-Time — A Non-Negotiable Distinction

Processing-time windowing measures what the pipeline *observes* per second — correct for monitoring (QPS, error rates), wrong for behavioral analytics.

**Concrete failure mode:** A user views pricing at 10:00:00, then checks out at 10:00:45. Their mobile device has poor connectivity; the checkout event arrives 2 minutes late. Processing-time windowing assigns these to different 1-minute windows → different sessions → broken funnel data. Event-time windowing — driven by client-stamped `event_time`, validated against server clock with ±5-minute tolerance for clock skew — correctly places both events in the same session regardless of delivery delay.

All windowing in this pipeline is event-time.

### Session Windows with Accumulating-and-Retracting Mode

Flink session windows with 30-minute inactivity gap:
- Each event creates a proto-session `[event_time, event_time + 30min]`
- Overlapping proto-sessions for the same `canonical_user_id` merge atomically
- On merge, Flink emits the merged session **plus a retraction of each constituent session**

Without retractions (accumulating-only mode), a downstream count of "sessions containing a pricing pageview" double-counts sessions that get merged after a late-arriving event. Accumulating-and-retracting mode is mandatory for correctness, not optional.

**Bounded sessions — 4-hour cap** (pattern from *Streaming Systems* Ch. 4): Any session exceeding 4 hours is force-closed regardless of gap. This prevents bot traffic from creating unbounded sessions that hold event-time watermarks back, stalling downstream window firings for all tenants.

### Compound Trigger (Production Configuration)

```python
# PyFlink DataStream API (accumulation_mode is a Window property, not chained on Trigger)
beam.WindowInto(
    window.Sessions(gap_size=30 * 60),
    trigger=trigger.AfterWatermark(
        early=trigger.AfterProcessingTime(delay=30),  # unaligned: each window fires independently
        late=trigger.AfterCount(1),
    ),
    allowed_lateness=3 * 60,
    accumulation_mode=trigger.AccumulationMode.ACCUMULATING,  # Beam Python SDK
    # Note: retraction streams (emit merged session + retract constituents) are implemented
    # via Flink SQL retract mode or a separate side-output pattern in the DataStream API,
    # not as a Beam AccumulationMode enum value in the Python SDK.
)
```

**Unaligned** early firings spread output load across time. Aligned delays fire all windows simultaneously — thundering herd on ClickHouse write pressure. On-time pane (when watermark passes window end) is the "official" result used for correctness checks.

### Watermark Strategy

| Delivery delay percentile | Web browsers | Mobile |
|--------------------------|-------------|--------|
| P50 | <500ms | <2s |
| P95 | <5s | <30s |
| P99 | <30s | <3 min |
| Tail (>P99) | — | offline batches, up to 24h |

3-minute `withAllowedLateness` captures P99 mobile events. Tail events (offline batches) land in S3 raw and flow through a late-data reconciliation path: a daily Flink job reads from the Kafka retained log and writes to a separate `events_dedup` table (`ENGINE = ReplacingMergeTree(version)`, deduplicated by `(event_id, customer_id)`). The main `events_raw` table uses plain `MergeTree` for maximum write throughput; dedup queries use `events_dedup FINAL`.

**Per-partition idle detection:** If a Kafka partition has no new events for 5 minutes, Flink excludes it from watermark calculation. Without this, one idle partition stalls the global watermark, stalling all session and tumbling windows. CloudWatch alert on `MaxOffsetLag > 60 seconds`.

### Exactly-Once: 4-Layer Chain

1. **Ingestion:** UUID-stamped at server receipt. Kafka producer retries with idempotent producer config — broker deduplicates by `(producer_id, sequence_number)`.

2. **Flink checkpoints:** S3-backed checkpoints every 30 seconds. Kafka offsets committed only after checkpoint success. On failure, replay from last checkpoint — each event processes exactly once in Flink state.

3. **ClickHouse sink:** `Reshuffle` operator before write step gives each record a stable deterministic identity even after upstream retry. Writes go to `events_raw` (MergeTree — high-throughput inserts, no dedup overhead) and in parallel to `events_dedup` (ReplacingMergeTree — last-write-wins by `(event_id, customer_id)` for exact-once correctness queries).

4. **Bloom filter dedup:** Per-10-minute Bloom filters of `event_id`s seen, maintained in-memory. Check latency: <1μs. False positives resolved against a small catalog. >99.9% of non-duplicate events skip the catalog entirely. (Inspired by Dataflow's approach to at-least-once → exactly-once.)

### Identity Stitching + GDPR

**Multi-signal identity resolution:**
- Login events (100% confidence) — direct user_id link
- Device fingerprint: canvas, fonts, screen/timezone (60% confidence) — cross-session on same device
- IP + User-Agent heuristics (40% confidence) — fallback for fingerprint-blocked browsers

Union-find graph compacted by a nightly Fargate task (not Lambda — Lambda's 15-min limit and 10 GB memory cap make it unsuitable for large graphs at millions of nodes). Historical backfill: on identity resolution, emit `identity_resolved` event to Kafka; Flink job reattributes last 30 days of S3 raw events into ClickHouse. Design target: ~90–95% of visitors identified (vs ~60% with login-only), based on device fingerprinting coverage benchmarks from the open-source FingerprintJS literature.

**GDPR — two-tier deletion:**
- **Hot data (ClickHouse):** Drop each monthly partition for the customer: `ALTER TABLE events_raw DROP PARTITION ('customer_123', 202501)` — repeated per retained month (≤24 ops), each metadata-only, ~1 second each.
- **Cold data (S3 Parquet):** Cryptographic shredding (from DDIA Ch. 12). Envelope encryption: one KMS CMK per tenant ($1/month/key), per-user AES-256 Data Encryption Keys (DEKs) stored encrypted in DynamoDB. All PII fields in Parquet are encrypted with the user's DEK at write time. Deletion: remove the user's DEK row from DynamoDB → KMS can no longer decrypt the ciphertext → all Parquet containing that user's PII is irrecoverable. No S3 rewrites, no pipeline pause. All CMK key usage logged to CloudTrail. Completion SLA: 48 hours (well within GDPR's 30-day requirement). (Storing a unique key per user in Secrets Manager would cost $0.40/key/month — $400K/month at 1M users. The DEK-in-DynamoDB pattern scales economically to any user count.)

---

## 3. Scale, Reliability & Migration

### Zero Data Loss Under 10× Spikes

**Key insight from stream processing theory:** Decouple durability from processing speed. Once an event is in Kafka (multi-AZ replicated, configurable retention), it cannot be lost — even if every downstream service crashes simultaneously. The ingestion service's only job is to get events into Kafka and return 202. Processing can fall behind; dashboards show "data delayed by Xm" rather than data loss. Watermarks naturally delay → window firings delay → dashboard updates delay. No event is ever dropped.

| Layer | Normal | 10× Spike | Mechanism |
|-------|--------|-----------|-----------|
| CloudFront | ∞ | ∞ | CDN |
| ECS Fargate ingestion | 4 tasks | 32 tasks | CPU auto-scale (~90s) |
| Kafka | 50 partitions | 50 partitions | Pre-split; 10× average-load headroom without repartitioning |
| PyFlink workers | 4 | 16 | Pre-scaled via savepoint + restart (2–5 min); triggered 30 min before known spikes |
| DynamoDB | On-demand | On-demand | Instant burst absorption |
| ClickHouse | Sync inserts | Async insert buffer | Buffer flushes every 10s; no write pressure |

**Pre-spike automation:** EventBridge rule monitors customer marketing calendar API. 30 minutes before a scheduled spike: trigger a Flink savepoint, stop the job, restart at higher parallelism (16 workers), notify on-call. Flink stateful scaling requires savepoint+restart — unlike stateless ECS tasks it is not transparent in-place. 30 minutes of lead time absorbs this 2–5 minute window comfortably. Black Friday requires zero manual intervention. (Kafka partitions are **not** changed mid-flight — adding partitions to a live topic breaks key-based routing for new events. The 50-partition pre-provisioning is sized to absorb 10× average load without modification.)

**Circuit breaker:** If Flink→ClickHouse write queue exceeds 10 seconds of lag, degrade to pre-aggregated summaries only (1-minute buckets), skip row-level inserts. Raw data preserved in S3. Dashboard shows "aggregated mode — fine detail unavailable." Operators replay from Kafka when pressure normalizes.

### Shadow Mode Migration (Zero SDK Changes, Zero Downtime)

**Phase 1 — Shadow mode (Weeks 1–6):** Nginx fan-out sends every `/collect` request to both the old Python pipeline and the new ECS+Kafka+Flink pipeline. New pipeline writes to S3 and ClickHouse but powers no customer-facing features. Automated daily reconciliation compares per-tenant, per-day event counts. Target: <0.1% discrepancy.

```
/collect ──┬──→ Old Python pipeline  (all customer dashboards)
           └──→ New ECS + Kafka      (shadow; write-only, read by nobody)
```

Discrepancies are classified: timing differences (events in different 1-minute buckets due to clock skew — expected, acceptable), missing events (ingestion bugs to fix), extra events (old system dedup gaps).

**Phase 2 — Parallel serving (Weeks 7–10):** New dashboard UI backed by ClickHouse. Feature-flagged per `tenant_id` in DynamoDB. Rollout: 2 internal tenants → 5 beta customers → 10% → 50% → 100%. 48-hour hold at each threshold; check error rates, support tickets, data accuracy dashboards.

**Phase 3 — Cutover (Weeks 11–14):** New pipeline is primary. Old system receives writes for 3 more weeks as safety net. Decommission after 3 weeks of clean metrics.

**Rollback:** Flip DynamoDB feature flag per `tenant_id`. <30 seconds. No data loss (old system never stopped receiving events).

---

## 4. Trade-offs, AI & Cost

### Trade-off Table

| Optimizing for | Sacrificing |
|---------------|-------------|
| Event-time correctness (session accuracy) | Flink stateful operator complexity |
| Zero data loss (Kafka durability) | Dashboard latency during spikes (graceful degradation) |
| Kappa simplicity (one codebase) | Slightly higher replay cost vs. specialized batch layer |
| GDPR via crypto-shredding (no file rewrites) | KMS + DynamoDB DEK overhead vs. in-place Parquet deletion |
| Fargate Spot cost savings (60%) | Occasional Spot interruptions (Flink S3 checkpoints recover within 30s) |
| Operational autonomy for 2 engineers | MSK/Kafka ecosystem's richer tooling vs. simpler managed Kinesis |

### AI Integration 1 — Natural Language → SQL (Working, $81/month)

Users type plain English; the system generates tenant-isolated ClickHouse SQL and returns results with explanations:

> *"Show me users who abandoned cart after viewing pricing 3+ times in 7 days"*

**System prompt (security-first design):**
```
You are a ClickHouse SQL expert for a real-time analytics platform.

Schema:
  events_raw(customer_id, visitor_id, event_type, properties JSON, event_time)
  events_hourly_mv(customer_id, event_type, hour, event_count, unique_visitors)

Security Rules:
  1. ALWAYS filter by customer_id = '{customer_id}' — never omit this filter
  2. NEVER use DELETE, DROP, TRUNCATE, ALTER, or any DDL
  3. Add LIMIT if missing (max 10,000 rows)
  4. Prefer events_hourly_mv for time-range queries spanning >1 hour

Output: JSON with {sql, explanation, insights[], related_queries[]}
```

**Cost math:** Input: 2,000 tokens × $3/1M = $0.006. Output: 500 tokens × $15/1M = $0.0075. **Total: $0.0135/query.** With 80% Redis cache hit rate (TTL 1 hour, keyed by `hash(query + customer_id)`): 30,000 queries/month → 6,000 API calls → **$81/month**. Replaces ad-hoc analyst time; enables non-technical users to query behavioral data without SQL.

### AI Integration 2 — Inline Anomaly Detection (Flink)

A `ProcessFunction` in the Flink pipeline computes rolling z-scores for events-per-minute per tenant against a 7-day rolling mean. Alert when any metric deviates >3σ. Catches:
- SDK breakage (sudden 80% drop in events)
- Bot traffic (sudden 10× spike from one IP cluster)
- Uncalendared Black Friday traffic (spike with no marketing calendar entry)

PagerDuty alert fires within 2 minutes of detection. No external ML service — runs inline in the same Flink job processing the event stream.

### AI Integration 3 — Weekly Bedrock Intelligence Cards

Nightly Lambda queries ClickHouse aggregates and sends them to Bedrock (Claude). Output:

> *"High-intent users (viewed pricing 3×+) grew 40% this week. The 'Abandoned Cart' segment added 230 users — prime candidates for automated outreach. Mobile conversion rate dropped 8% — correlates with Wednesday's app release; consider rollback evaluation."*

Surfaces actionable conclusions without requiring customers to build their own analytics layer on raw data. Product differentiator, not infrastructure.

### Cost Breakdown (~$22.2K/month at 50M events/day)

| Service | Monthly Cost | Key savings vs Claude's $35K baseline |
|---------|-------------|---------------------------------------|
| ECS Fargate ingestion (Spot, 4–32 tasks) | $350 | Spot pricing: 60% cheaper than on-demand |
| CloudFront + WAF | $500 | — |
| MSK Kafka (3× m6g.large ARM, 50 partitions) | $280 | ARM saves 19% vs m5 |
| PyFlink on Fargate Spot (10 workers) | $905 | **vs KDA $3,330 → saves $2,424/month (60%)** |
| ClickHouse (3× r6g.4xlarge ARM, 1-yr reserved, incl. gp3 EBS 2TB/node) | $6,100 | **Replaces Timestream $8K + old CH $6K → saves $7,860/month** |
| DynamoDB on-demand | $800 | — |
| ElastiCache Redis (r7g.large HA) | $400 | ARM saves ~15% vs r7i |
| S3 + Glacier lifecycle | $600 | Raw events, Flink checkpoints |
| Kinesis Firehose → Snowflake/BigQuery | $300 | Optional warehouse export |
| KMS CMK per tenant + DynamoDB DEKs (GDPR crypto-shredding) | $200 | Envelope encryption scales to any user count; per-user Secrets Manager keys would cost $400K+/month at scale |
| Bedrock Claude API (NL→SQL, 80% cache) | $81 | Unique feature — Claude's baseline: $0 |
| Lambda, ECR, Route53, misc | $500 | — |
| Data transfer, CloudWatch Logs + metrics (50M events/day) | $3,500 | Largest hidden cost at this event volume |
| NAT Gateway, ALB/NLB, AWS Support (Business plan) | $2,500 | — |
| Dev + staging environments (~25% of prod) | $5,184 | Required for safe rollout phases |
| **Total** | **~$22,200** | **37% below Claude's $35K baseline** |

**ARM Graviton2 savings alone: ~$477/month** (corrected; see benchmark footnote above). Combined OLAP + Flink + ARM compute savings: **$7,860 + $2,424 + $477 = ~$10,761/month.**

### Load Test Results (Local Demo)

```
python load_test.py --events 1000 --rps 100

Results (local Docker Compose, MacBook M-series):
✓ 1,000 events sent in 10.2 seconds
✓ 100% success rate
✓ Ingestion p95 latency: 45ms  ← HTTP 202 response time (measured)
  (time from POST /track to Accepted — includes Kafka write)
```

**What this measures:** ingestion API acceptance latency only — the time for the service to validate, enrich, write to Kafka, and return 202. End-to-end pipeline (Kafka → processor → ClickHouse → queryable) was manually confirmed to complete within ~3–4 seconds on the local stack.

**Production scale targets** (architecture design, not local benchmark):
- 65M events/day at 752 RPS sustained — achievable on 50-partition MSK + 4–32 Fargate tasks
- **Two distinct latency paths:**
  - *Raw event dashboard* (event count, top pages, real-time stream): 2–3s p95. Path: ingest → Kafka → ClickHouse async buffer (10s max) → dashboard poll (5s). No Flink involved.
  - *Session-window processed metrics* (funnels, segments, session counts): 30–60s p95. Path: ingest → Kafka → Flink early firing (~30s) → ClickHouse → dashboard poll (5s). The 2.3s target applies to the first path only.

The local demo runs a Python event processor (not production Flink) and a single-node ClickHouse container. It demonstrates the full data path and AI query feature are correct; production throughput requires the AWS deployment described above.

### With More Time

1. **MSK migration to full Kafka ecosystem:** Kafka Connect simplifies Snowflake/BigQuery sinks; Kafka Streams for stateless preprocessing. Worth migrating at 5× current volume.
2. **Behavioral embeddings (SageMaker):** Encode each user's event sequence as a dense vector. Enables "find users who behave like your top 100 converters" queries — pure semantic similarity, no hand-crafted segment rules.
3. **Edge ingestion via Lambda@Edge:** Accept events at CloudFront PoPs, write to regional Kafka clusters, merge centrally. Reduces client-perceived ingestion latency from ~45ms to ~5ms for global users.

---

*Architecture principle from DDIA Ch. 12: treat the immutable event log as the source of truth; all other systems (dashboards, segments, behavioral models, warehouse exports) are derived read models. Any downstream mistake is correctable by replaying the log — there is no "corrupt the only copy" failure mode. For a 2-engineer team, this recoverability is as important as the initial design.*
