"""
Simplified Stream Processor (without PyFlink)
For local development and testing
Reads from Kafka and writes to ClickHouse
"""

import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Any

from kafka import KafkaConsumer
from clickhouse_driver import Client
import redis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class StreamProcessor:
    def __init__(
        self,
        kafka_bootstrap_servers: List[str],
        clickhouse_host: str,
        redis_host: str,
        batch_size: int = 100,
        flush_interval: int = 5
    ):
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.batch: List[Dict[str, Any]] = []
        self.last_flush_time = time.time()

        # Initialize Kafka consumer
        self.consumer = KafkaConsumer(
            'events-raw',
            bootstrap_servers=kafka_bootstrap_servers,
            auto_offset_reset='latest',
            enable_auto_commit=True,
            group_id='simple-processor',
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )
        logger.info("Kafka consumer initialized")

        # Initialize ClickHouse client
        self.clickhouse = Client(
            host=clickhouse_host,
            port=9000,
            database='analytics',
            user='admin',
            password='password'
        )
        logger.info("ClickHouse client initialized")

        # Initialize Redis client
        self.redis = redis.Redis(
            host=redis_host,
            port=6379,
            db=1,
            decode_responses=True
        )
        logger.info("Redis client initialized")

    def process_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single event
        - Enrich with identity stitching
        - Normalize data
        """
        try:
            # Identity stitching
            visitor_id = event.get('visitor_id')
            user_id = event.get('user_id')
            customer_id = event.get('customer_id')

            if visitor_id and customer_id:
                # If event has user_id, store the mapping
                if user_id:
                    redis_key = f"identity:{customer_id}:{visitor_id}"
                    self.redis.set(redis_key, user_id, ex=86400 * 90)

                # If no user_id, try to look it up
                elif not user_id:
                    redis_key = f"identity:{customer_id}:{visitor_id}"
                    stored_user_id = self.redis.get(redis_key)
                    if stored_user_id:
                        event['user_id'] = stored_user_id
                        event['identity_stitched'] = True

            # Ensure timestamp is properly formatted
            if 'timestamp' not in event or not event['timestamp']:
                event['timestamp'] = datetime.utcnow().isoformat()

            # Ensure properties is a JSON string
            if isinstance(event.get('properties'), dict):
                event['properties'] = json.dumps(event['properties'])
            elif not event.get('properties'):
                event['properties'] = '{}'

            return event

        except Exception as e:
            logger.error(f"Error processing event: {e}")
            return event

    def flush_to_clickhouse(self):
        """
        Flush batch of events to ClickHouse
        """
        if not self.batch:
            return

        try:
            rows = []
            for event in self.batch:
                row = (
                    event.get('customer_id', ''),
                    event.get('visitor_id', ''),
                    event.get('user_id'),
                    event.get('session_id', ''),
                    event.get('event_type', ''),
                    event.get('event_name', ''),
                    event.get('properties', '{}'),
                    event.get('page_url'),
                    event.get('referrer'),
                    event.get('user_agent'),
                    event.get('ip_address'),
                    event.get('timestamp', datetime.utcnow().isoformat())
                )
                rows.append(row)

            # Insert into ClickHouse
            self.clickhouse.execute(
                """
                INSERT INTO events_raw
                (customer_id, visitor_id, user_id, session_id, event_type, event_name,
                 properties, page_url, referrer, user_agent, ip_address, timestamp)
                VALUES
                """,
                rows
            )

            logger.info(f"✓ Flushed {len(self.batch)} events to ClickHouse")

            # Clear batch
            self.batch = []
            self.last_flush_time = time.time()

        except Exception as e:
            logger.error(f"✗ Error flushing to ClickHouse: {e}")

    def run(self):
        """
        Main processing loop
        """
        logger.info("Starting stream processor...")
        logger.info(f"Batch size: {self.batch_size}, Flush interval: {self.flush_interval}s")

        try:
            for message in self.consumer:
                try:
                    event = message.value

                    # Process event
                    processed_event = self.process_event(event)

                    # Add to batch
                    self.batch.append(processed_event)

                    # Flush if batch is full or time threshold exceeded
                    current_time = time.time()
                    time_since_flush = current_time - self.last_flush_time

                    if len(self.batch) >= self.batch_size or time_since_flush >= self.flush_interval:
                        self.flush_to_clickhouse()

                except Exception as e:
                    logger.error(f"Error processing message: {e}")

        except KeyboardInterrupt:
            logger.info("Shutting down processor...")
            self.flush_to_clickhouse()
            self.consumer.close()


if __name__ == "__main__":
    processor = StreamProcessor(
        kafka_bootstrap_servers=['localhost:9092'],
        clickhouse_host='localhost',
        redis_host='localhost',
        batch_size=100,
        flush_interval=5
    )

    processor.run()
