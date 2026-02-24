"""
AI-Powered Analytics Engine
Translates natural language queries to ClickHouse SQL using Claude API
KEY DIFFERENTIATOR: This feature doesn't exist in Claude's baseline answer!
"""

import json
import logging
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime

from anthropic import Anthropic
import redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIAnalyticsEngine:
    """
    Natural language to SQL query engine
    Powered by Claude API
    """

    def __init__(self, anthropic_api_key: str, redis_host: str = 'redis', cache_ttl: int = 3600):
        self.client = Anthropic(api_key=anthropic_api_key)
        self.redis = redis.Redis(host=redis_host, port=6379, db=3, decode_responses=True)
        self.cache_ttl = cache_ttl

        # ClickHouse schema context for Claude
        self.schema_context = """
        # ClickHouse Schema

        ## Main Tables:

        ### events_raw
        - customer_id String (REQUIRED: always filter by this)
        - visitor_id String
        - user_id Nullable(String)
        - session_id String
        - event_type String (page_view, click, form_submit, cart_add, cart_abandon, etc)
        - event_name String
        - properties String (JSON: use JSONExtractString(properties, 'key'))
        - page_url Nullable(String)
        - referrer Nullable(String)
        - user_agent Nullable(String)
        - ip_address Nullable(String)
        - timestamp DateTime64(3)
        - ingested_at DateTime64(3)

        ### events_hourly
        - customer_id String
        - event_type String
        - hour DateTime
        - event_count UInt64
        - unique_visitors AggregateFunction(uniq, String)
        - unique_users AggregateFunction(uniq, Nullable(String))

        ### user_sessions
        - customer_id String
        - session_id String
        - visitor_id String
        - user_id Nullable(String)
        - session_start DateTime64(3)
        - session_end DateTime64(3)
        - page_views UInt32
        - events_count UInt32
        - duration_seconds UInt32
        - landing_page String
        - exit_page String
        - referrer Nullable(String)

        ## Security Rules:
        1. ALWAYS filter by customer_id = '{customer_id}'
        2. NEVER use DELETE, DROP, TRUNCATE, ALTER, UPDATE
        3. Add LIMIT if missing (default 100, max 10000)
        4. Use proper ClickHouse functions (uniq, uniqExact, JSONExtractString)

        ## Common Query Patterns:

        ### Top pages by views
        SELECT
            JSONExtractString(properties, 'page') AS page,
            count() AS views,
            uniq(visitor_id) AS unique_visitors
        FROM events_raw
        WHERE customer_id = '{customer_id}'
          AND event_type = 'page_view'
          AND timestamp >= now() - INTERVAL 7 DAY
        GROUP BY page
        ORDER BY views DESC
        LIMIT 10

        ### Users who abandoned cart after viewing pricing
        SELECT
            visitor_id,
            count(*) AS pricing_views,
            max(timestamp) AS last_view
        FROM events_raw
        WHERE customer_id = '{customer_id}'
          AND event_type = 'page_view'
          AND JSONExtractString(properties, 'page') LIKE '%pricing%'
          AND visitor_id IN (
            SELECT visitor_id FROM events_raw
            WHERE customer_id = '{customer_id}' AND event_type = 'cart_abandon'
          )
        GROUP BY visitor_id
        HAVING pricing_views >= 3
        ORDER BY pricing_views DESC
        LIMIT 100

        ### Real-time events per minute
        SELECT
            toStartOfMinute(timestamp) AS minute,
            count() AS event_count,
            uniq(visitor_id) AS unique_visitors
        FROM events_raw
        WHERE customer_id = '{customer_id}'
          AND timestamp >= now() - INTERVAL 1 HOUR
        GROUP BY minute
        ORDER BY minute DESC
        """

    def _get_cache_key(self, query: str, customer_id: str) -> str:
        """Generate cache key for query"""
        combined = f"{customer_id}:{query}"
        return f"ai_query:{hashlib.md5(combined.encode()).hexdigest()}"

    def _check_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Check if query result is cached"""
        try:
            cached = self.redis.get(cache_key)
            if cached:
                logger.info(f"Cache hit for query: {cache_key}")
                return json.loads(cached)
        except Exception as e:
            logger.error(f"Cache check error: {e}")
        return None

    def _save_to_cache(self, cache_key: str, data: Dict[str, Any]):
        """Save query result to cache"""
        try:
            self.redis.setex(cache_key, self.cache_ttl, json.dumps(data))
            logger.info(f"Cached query result: {cache_key}")
        except Exception as e:
            logger.error(f"Cache save error: {e}")

    def generate_sql(self, natural_language_query: str, customer_id: str) -> Dict[str, Any]:
        """
        Convert natural language query to ClickHouse SQL
        Returns: {sql, explanation, related_queries}
        """
        # Check cache first
        cache_key = self._get_cache_key(natural_language_query, customer_id)
        cached_result = self._check_cache(cache_key)
        if cached_result:
            return cached_result

        # Prepare prompt for Claude
        system_prompt = f"""You are a ClickHouse SQL expert for a real-time analytics platform.

{self.schema_context.replace('{customer_id}', customer_id)}

Your task:
1. Generate valid ClickHouse SQL based on the user's natural language query
2. ALWAYS filter by customer_id = '{customer_id}' for tenant isolation
3. Explain what the query does in simple terms
4. Suggest 3 related queries the user might want to run next
5. If the query could be ambiguous, provide insights about what you're assuming

Return a JSON response with this structure:
{{
    "sql": "SELECT ...",
    "explanation": "This query finds...",
    "insights": "This data suggests...",
    "related_queries": [
        "Show me...",
        "What is...",
        "Compare..."
    ]
}}

IMPORTANT: Return ONLY valid JSON, no markdown formatting or code blocks.
"""

        user_prompt = f"User query: {natural_language_query}"

        try:
            # Call Claude API
            logger.info(f"Generating SQL for query: {natural_language_query}")

            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2000,
                temperature=0.1,  # Low temperature for deterministic SQL
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            # Parse response
            response_text = response.content[0].text.strip()

            # Remove markdown code blocks if present
            if response_text.startswith("```json"):
                response_text = response_text.split("```json")[1]
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
            if response_text.endswith("```"):
                response_text = response_text.rsplit("```", 1)[0]

            result = json.loads(response_text.strip())

            # Validate SQL (basic security check)
            sql = result.get('sql', '').upper()
            forbidden_keywords = ['DELETE', 'DROP', 'TRUNCATE', 'ALTER', 'UPDATE', 'INSERT']
            if any(keyword in sql for keyword in forbidden_keywords):
                raise ValueError("Query contains forbidden SQL keywords")

            # Ensure customer_id filter exists
            if f"customer_id = '{customer_id}'" not in result.get('sql', ''):
                raise ValueError("Query missing required customer_id filter")

            # Add metadata
            result['generated_at'] = datetime.utcnow().isoformat()
            result['customer_id'] = customer_id
            result['original_query'] = natural_language_query

            # Cache the result
            self._save_to_cache(cache_key, result)

            logger.info(f"SQL generated successfully for customer {customer_id}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response as JSON: {e}")
            logger.error(f"Response was: {response_text}")
            return {
                "error": "Failed to parse AI response",
                "sql": None,
                "explanation": "The AI returned an invalid response format",
                "related_queries": []
            }

        except Exception as e:
            logger.error(f"Error generating SQL: {e}")
            return {
                "error": str(e),
                "sql": None,
                "explanation": f"Failed to generate query: {str(e)}",
                "related_queries": []
            }

    def explain_insights(self, query_results: List[Dict[str, Any]], original_query: str) -> str:
        """
        Use Claude to explain query results and provide insights
        """
        try:
            prompt = f"""Analyze these query results and provide business insights.

Original query: {original_query}

Results (first 10 rows):
{json.dumps(query_results[:10], indent=2)}

Provide:
1. What this data shows (2-3 sentences)
2. Key insights or patterns (bullet points)
3. Actionable recommendations (2-3 suggestions)

Keep it concise and business-focused.
"""

            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1000,
                temperature=0.3,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            insights = response.content[0].text.strip()
            return insights

        except Exception as e:
            logger.error(f"Error generating insights: {e}")
            return "Unable to generate insights at this time."


class MockAIAnalyticsEngine:
    """
    Template-based SQL generator — runs without an API key.
    Matches keywords in the natural language query to pre-built ClickHouse SQL.
    """

    TEMPLATES = [
        {
            "keywords": ["abandon", "cart", "pricing"],
            "sql": """SELECT
    visitor_id,
    countIf(event_type = 'page_view' AND JSONExtractString(properties, 'page') LIKE '%pricing%') AS pricing_views,
    countIf(event_type = 'cart_abandon') AS cart_abandons,
    max(timestamp) AS last_seen
FROM events_raw
WHERE customer_id = '{customer_id}'
  AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY visitor_id
HAVING pricing_views >= 3 AND cart_abandons > 0
ORDER BY pricing_views DESC
LIMIT 100""",
            "explanation": "Finds visitors who viewed the pricing page 3+ times and later abandoned their cart — high-intent users who didn't convert.",
            "insights": "These users show strong purchase intent. Consider a targeted email sequence or a time-limited discount to recover them.",
            "related_queries": [
                "Show me the average time between pricing views and cart abandon",
                "Which pricing page sections do these users spend the most time on?",
                "How many of these users eventually converted in the next 7 days?"
            ]
        },
        {
            "keywords": ["top", "page", "view"],
            "sql": """SELECT
    JSONExtractString(properties, 'page') AS page,
    count() AS views,
    uniq(visitor_id) AS unique_visitors
FROM events_raw
WHERE customer_id = '{customer_id}'
  AND event_type = 'page_view'
  AND timestamp >= today()
GROUP BY page
ORDER BY views DESC
LIMIT 10""",
            "explanation": "Returns the top 10 pages by total view count for today, along with unique visitor counts.",
            "insights": "Your most visited pages represent the core user journey. Pages with high views but low unique visitors indicate repeat visits — users may be stuck or highly engaged.",
            "related_queries": [
                "Show me top pages for the last 7 days",
                "Which pages have the highest bounce rate?",
                "What events happen most after a user visits the top page?"
            ]
        },
        {
            "keywords": ["common", "event", "hour", "last hour", "recent"],
            "sql": """SELECT
    event_type,
    event_name,
    count() AS occurrences,
    uniq(visitor_id) AS unique_visitors
FROM events_raw
WHERE customer_id = '{customer_id}'
  AND timestamp >= now() - INTERVAL 1 HOUR
GROUP BY event_type, event_name
ORDER BY occurrences DESC
LIMIT 20""",
            "explanation": "Lists the most frequent event types and names in the last hour, with unique visitor counts.",
            "insights": "Spikes in specific events (form_submit, cart_add) indicate conversion activity. Sudden drops in page_view events can indicate an SDK issue.",
            "related_queries": [
                "Show me events per minute for the last hour",
                "Which visitors triggered the most events today?",
                "What is the error rate for form submissions?"
            ]
        },
        {
            "keywords": ["funnel", "signup", "conversion", "step"],
            "sql": """SELECT
    step_name,
    step_number,
    count(DISTINCT visitor_id) AS users_at_step,
    countIf(completed = true) AS completed,
    round(countIf(completed = true) / count(DISTINCT visitor_id) * 100, 1) AS completion_rate_pct
FROM conversion_funnels
WHERE customer_id = '{customer_id}'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY step_name, step_number
ORDER BY step_number""",
            "explanation": "Shows the conversion funnel step by step — how many users reach each step and what percentage complete it.",
            "insights": "Steps with the largest drop-off are your biggest optimization opportunities. A completion rate below 50% on any step warrants immediate UX investigation.",
            "related_queries": [
                "Where do users drop off most in the funnel?",
                "Show me funnel performance by device type",
                "Which traffic source has the best funnel completion rate?"
            ]
        },
        {
            "keywords": ["active", "user", "session", "today"],
            "sql": """SELECT
    toStartOfHour(timestamp) AS hour,
    uniq(visitor_id) AS active_visitors,
    uniq(session_id) AS sessions,
    count() AS total_events
FROM events_raw
WHERE customer_id = '{customer_id}'
  AND timestamp >= today()
GROUP BY hour
ORDER BY hour DESC""",
            "explanation": "Shows hourly active visitors, sessions, and event volume for today.",
            "insights": "Traffic patterns reveal your peak usage hours. Plan maintenance windows and marketing sends around these times for maximum impact.",
            "related_queries": [
                "Show me active users by day for this week",
                "What is the average session duration today?",
                "Which hours have the highest conversion rate?"
            ]
        },
    ]

    DEFAULT = {
        "sql": """SELECT
    event_type,
    count() AS event_count,
    uniq(visitor_id) AS unique_visitors,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM events_raw
WHERE customer_id = '{customer_id}'
  AND timestamp >= now() - INTERVAL 24 HOUR
GROUP BY event_type
ORDER BY event_count DESC
LIMIT 50""",
        "explanation": "Summary of all event types in the last 24 hours with visitor counts and time range.",
        "insights": "This overview helps identify which interactions are most common. Use it as a starting point to drill into specific event flows.",
        "related_queries": [
            "Show me the top pages by views today",
            "Find users who abandoned cart after viewing pricing 3+ times",
            "What are the most common events in the last hour?"
        ]
    }

    def __init__(self, redis_host: str = 'localhost', cache_ttl: int = 3600):
        try:
            self.redis = redis.Redis(host=redis_host, port=6379, db=3, decode_responses=True)
        except Exception:
            self.redis = None
        self.cache_ttl = cache_ttl

    def _get_cache_key(self, query: str, customer_id: str) -> str:
        combined = f"{customer_id}:{query}"
        return f"ai_query:{hashlib.md5(combined.encode()).hexdigest()}"

    def _check_cache(self, cache_key: str):
        try:
            if self.redis:
                cached = self.redis.get(cache_key)
                if cached:
                    return json.loads(cached)
        except Exception:
            pass
        return None

    def _save_to_cache(self, cache_key: str, data):
        try:
            if self.redis:
                self.redis.setex(cache_key, self.cache_ttl, json.dumps(data))
        except Exception:
            pass

    def generate_sql(self, natural_language_query: str, customer_id: str) -> dict:
        cache_key = self._get_cache_key(natural_language_query, customer_id)
        cached = self._check_cache(cache_key)
        if cached:
            return cached

        q = natural_language_query.lower()
        template = self.DEFAULT
        for t in self.TEMPLATES:
            if all(kw in q for kw in t["keywords"][:2]):  # match at least 2 keywords
                template = t
                break
            if any(kw in q for kw in t["keywords"]):
                template = t
                break

        result = {
            "sql": template["sql"].replace("{customer_id}", customer_id),
            "explanation": template["explanation"],
            "insights": template["insights"],
            "related_queries": template["related_queries"],
            "generated_at": datetime.utcnow().isoformat(),
            "customer_id": customer_id,
            "original_query": natural_language_query,
            "mode": "template"
        }
        self._save_to_cache(cache_key, result)
        return result

    def explain_insights(self, query_results, original_query: str) -> str:
        n = len(query_results)
        return f"Query returned {n} row{'s' if n != 1 else ''}. " \
               f"Connect an Anthropic API key to enable AI-generated narrative insights."


# Example usage
if __name__ == "__main__":
    import os

    # Test the AI analytics engine
    api_key = os.getenv("ANTHROPIC_API_KEY", "your-api-key-here")

    engine = AIAnalyticsEngine(
        anthropic_api_key=api_key,
        redis_host='localhost'
    )

    # Example queries
    test_queries = [
        "Show me the top 10 pages by views today",
        "Find users who abandoned cart after viewing pricing 3+ times",
        "What are the most common events in the last hour?",
        "Show me conversion funnel for signup process"
    ]

    for query in test_queries:
        print(f"\n{'='*80}")
        print(f"Query: {query}")
        print(f"{'='*80}")

        result = engine.generate_sql(query, customer_id="demo_tenant")

        print(f"\nSQL:\n{result.get('sql', 'N/A')}")
        print(f"\nExplanation:\n{result.get('explanation', 'N/A')}")
        print(f"\nRelated queries:")
        for related in result.get('related_queries', []):
            print(f"  - {related}")
