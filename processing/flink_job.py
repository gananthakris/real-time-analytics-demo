"""
PyFlink Stream Processing Job
Reads events from Kafka, processes them, and writes to ClickHouse
"""

import json
import logging
from datetime import datetime
from typing import Iterator

from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import (
    KafkaSource,
    KafkaOffsetsInitializer,
    KafkaSink,
    KafkaRecordSerializationSchema
)
from pyflink.common import WatermarkStrategy, Types, Time
from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream.functions import MapFunction, ProcessFunction
from pyflink.datastream.state import ValueStateDescriptor
from clickhouse_driver import Client
import redis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EventEnrichment(MapFunction):
    """
    Enrich events with additional context
    - Parse JSON properties
    - Extract user agent details
    - Normalize timestamps
    """

    def map(self, value: str):
        try:
            event = json.loads(value)

            # Ensure timestamp is in correct format
            if 'timestamp' in event:
                # Convert ISO string to datetime if needed
                if isinstance(event['timestamp'], str):
                    event['timestamp'] = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
                else:
                    event['timestamp'] = datetime.fromisoformat(event['timestamp'])
            else:
                event['timestamp'] = datetime.utcnow()

            # Parse properties JSON if it's a string
            if isinstance(event.get('properties'), str):
                event['properties'] = json.loads(event['properties'])

            # Add processing metadata
            event['processed_at'] = datetime.utcnow().isoformat()

            return json.dumps(event)

        except Exception as e:
            logger.error(f"Error enriching event: {e}, event: {value}")
            return None


class IdentityStitching(ProcessFunction):
    """
    Identity stitching: link visitor_id to user_id when user logs in
    Uses Flink state to maintain visitor -> user mappings
    """

    def __init__(self):
        self.visitor_to_user_state = None

    def open(self, runtime_context):
        # Initialize state
        state_descriptor = ValueStateDescriptor(
            "visitor_to_user_mapping",
            Types.STRING()
        )
        self.visitor_to_user_state = runtime_context.get_state(state_descriptor)

        # Connect to Redis for persistent mapping
        self.redis_client = redis.Redis(
            host='redis',
            port=6379,
            db=1,  # Use different DB for identity stitching
            decode_responses=True
        )
        logger.info("Identity stitching processor initialized")

    def process_element(self, value: str, ctx: 'ProcessFunction.Context'):
        try:
            event = json.loads(value)

            visitor_id = event.get('visitor_id')
            user_id = event.get('user_id')
            customer_id = event.get('customer_id')

            if not visitor_id or not customer_id:
                yield value
                return

            # If event has user_id, create/update mapping
            if user_id:
                # Store in Flink state
                self.visitor_to_user_state.update(user_id)

                # Store in Redis for persistence across restarts
                redis_key = f"identity:{customer_id}:{visitor_id}"
                self.redis_client.set(redis_key, user_id, ex=86400 * 90)  # 90 days TTL

                logger.info(f"Stitched identity: visitor={visitor_id} -> user={user_id}")

            # If event doesn't have user_id, try to look it up
            elif not user_id:
                # Check Flink state first
                stored_user_id = self.visitor_to_user_state.value()

                # Fallback to Redis
                if not stored_user_id:
                    redis_key = f"identity:{customer_id}:{visitor_id}"
                    stored_user_id = self.redis_client.get(redis_key)

                # Enrich event with user_id if found
                if stored_user_id:
                    event['user_id'] = stored_user_id
                    event['identity_stitched'] = True
                    logger.debug(f"Applied identity: visitor={visitor_id} -> user={stored_user_id}")

            yield json.dumps(event)

        except Exception as e:
            logger.error(f"Error in identity stitching: {e}")
            yield value

    def close(self):
        if hasattr(self, 'redis_client'):
            self.redis_client.close()


class ClickHouseWriter(ProcessFunction):
    """
    Write events to ClickHouse
    Batches events for efficiency
    """

    def __init__(self, batch_size=100, flush_interval_ms=5000):
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms
        self.batch = []
        self.last_flush_time = None

    def open(self, runtime_context):
        # Initialize ClickHouse client
        self.clickhouse_client = Client(
            host='clickhouse',
            port=9000,
            database='analytics',
            user='admin',
            password='password'
        )
        self.last_flush_time = datetime.utcnow()
        logger.info("ClickHouse writer initialized")

    def process_element(self, value: str, ctx: 'ProcessFunction.Context'):
        try:
            event = json.loads(value)

            # Add to batch
            self.batch.append(event)

            # Flush if batch is full or time threshold exceeded
            current_time = datetime.utcnow()
            time_since_flush = (current_time - self.last_flush_time).total_seconds() * 1000

            if len(self.batch) >= self.batch_size or time_since_flush >= self.flush_interval_ms:
                self._flush_batch()

            yield value

        except Exception as e:
            logger.error(f"Error processing event for ClickHouse: {e}")

    def _flush_batch(self):
        """Flush accumulated events to ClickHouse"""
        if not self.batch:
            return

        try:
            # Prepare data for insertion
            rows = []
            for event in self.batch:
                row = (
                    event.get('customer_id', ''),
                    event.get('visitor_id', ''),
                    event.get('user_id'),
                    event.get('session_id', ''),
                    event.get('event_type', ''),
                    event.get('event_name', ''),
                    json.dumps(event.get('properties', {})),
                    event.get('page_url'),
                    event.get('referrer'),
                    event.get('user_agent'),
                    event.get('ip_address'),
                    event.get('timestamp', datetime.utcnow().isoformat())
                )
                rows.append(row)

            # Insert into ClickHouse
            self.clickhouse_client.execute(
                """
                INSERT INTO events_raw
                (customer_id, visitor_id, user_id, session_id, event_type, event_name,
                 properties, page_url, referrer, user_agent, ip_address, timestamp)
                VALUES
                """,
                rows
            )

            logger.info(f"Flushed {len(self.batch)} events to ClickHouse")

            # Clear batch
            self.batch = []
            self.last_flush_time = datetime.utcnow()

        except Exception as e:
            logger.error(f"Error flushing batch to ClickHouse: {e}")
            # Don't clear batch on error - will retry

    def close(self):
        # Flush any remaining events
        self._flush_batch()
        if hasattr(self, 'clickhouse_client'):
            self.clickhouse_client.disconnect()


class SegmentEvaluator(ProcessFunction):
    """
    Real-time segment evaluation
    Evaluates if user belongs to predefined segments
    """

    def open(self, runtime_context):
        self.redis_client = redis.Redis(
            host='redis',
            port=6379,
            db=2,  # Segments DB
            decode_responses=True
        )

        # Load segment definitions from Redis
        # In production, this would be loaded from a configuration service
        self._load_segments()

    def _load_segments(self):
        """Load segment definitions"""
        # Example segments
        self.segments = {
            'high_intent': {
                'conditions': [
                    {'event_type': 'page_view', 'count': 3, 'window_minutes': 30},
                    {'event_type': 'pricing_view', 'count': 2}
                ]
            },
            'cart_abandoners': {
                'conditions': [
                    {'event_type': 'cart_add'},
                    {'event_type': 'cart_abandon', 'window_minutes': 15}
                ]
            }
        }

    def process_element(self, value: str, ctx: 'ProcessFunction.Context'):
        try:
            event = json.loads(value)

            customer_id = event.get('customer_id')
            visitor_id = event.get('visitor_id')
            event_type = event.get('event_type')

            # Evaluate segments
            for segment_name, segment_def in self.segments.items():
                if self._evaluate_segment(customer_id, visitor_id, event_type, segment_def):
                    # Add user to segment
                    segment_key = f"segment:{customer_id}:{segment_name}"
                    self.redis_client.sadd(segment_key, visitor_id)
                    self.redis_client.expire(segment_key, 86400 * 30)  # 30 days

                    logger.info(f"Added {visitor_id} to segment {segment_name}")

            yield value

        except Exception as e:
            logger.error(f"Error in segment evaluation: {e}")
            yield value

    def _evaluate_segment(self, customer_id: str, visitor_id: str, event_type: str, segment_def: dict) -> bool:
        """Evaluate if user matches segment conditions"""
        # Simplified evaluation - in production, this would be more sophisticated
        # Could use Flink's CEP (Complex Event Processing) for advanced patterns
        return False  # Placeholder

    def close(self):
        if hasattr(self, 'redis_client'):
            self.redis_client.close()


def main():
    """
    Main Flink job
    """
    # Create execution environment
    env = StreamExecutionEnvironment.get_execution_environment()

    # Enable checkpointing for exactly-once semantics
    env.enable_checkpointing(60000)  # Checkpoint every 60 seconds

    # Set parallelism
    env.set_parallelism(4)

    # Add JARs for Kafka connector
    env.add_jars("file:///opt/flink/lib/flink-sql-connector-kafka-1.18.0.jar")

    # Configure Kafka source
    kafka_source = KafkaSource.builder() \
        .set_bootstrap_servers("kafka:29092") \
        .set_topics("events-raw") \
        .set_group_id("flink-processor") \
        .set_starting_offsets(KafkaOffsetsInitializer.latest()) \
        .set_value_only_deserializer(SimpleStringSchema()) \
        .build()

    # Create stream from Kafka
    events_stream = env.from_source(
        kafka_source,
        WatermarkStrategy.for_monotonous_timestamps(),
        "Kafka Events Source"
    )

    # Processing pipeline
    processed_stream = events_stream \
        .map(EventEnrichment(), output_type=Types.STRING()) \
        .filter(lambda x: x is not None) \
        .key_by(lambda x: json.loads(x).get('visitor_id', 'unknown')) \
        .process(IdentityStitching()) \
        .process(SegmentEvaluator()) \
        .process(ClickHouseWriter())

    # Print to console for debugging
    processed_stream.print()

    # Execute job
    logger.info("Starting Flink job: Real-Time Analytics Processing")
    env.execute("Real-Time Analytics Processing")


if __name__ == "__main__":
    main()
