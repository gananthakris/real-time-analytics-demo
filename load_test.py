#!/usr/bin/env python3
"""
Load Testing Script for Real-Time Analytics Pipeline
Tests ingestion throughput and latency
"""

import argparse
import asyncio
import aiohttp
import time
import random
from datetime import datetime
import uuid
import json
from typing import List, Dict


class LoadTester:
    def __init__(self, api_url: str, customer_id: str):
        self.api_url = api_url
        self.customer_id = customer_id
        self.results = {
            'total_sent': 0,
            'total_successful': 0,
            'total_failed': 0,
            'latencies': [],
            'errors': []
        }

    def generate_event(self) -> Dict:
        """Generate a random event"""
        event_types = [
            ('page_view', 'Page View'),
            ('button_click', 'Button Click'),
            ('form_submit', 'Form Submit'),
            ('cart_add', 'Add to Cart'),
            ('cart_abandon', 'Cart Abandon'),
            ('pricing_view', 'Pricing Page View'),
            ('signup_start', 'Signup Started')
        ]

        pages = ['/', '/pricing', '/features', '/docs', '/signup', '/login']

        event_type, event_name = random.choice(event_types)

        return {
            'customer_id': self.customer_id,
            'visitor_id': f'visitor_{random.randint(1, 100)}',
            'user_id': f'user_{random.randint(1, 50)}' if random.random() > 0.5 else None,
            'session_id': f'session_{uuid.uuid4().hex[:8]}',
            'event_type': event_type,
            'event_name': event_name,
            'properties': {
                'page': random.choice(pages),
                'test': True,
                'load_test_run': datetime.utcnow().isoformat()
            },
            'page_url': f'https://example.com{random.choice(pages)}',
            'timestamp': datetime.utcnow().isoformat()
        }

    async def send_event(self, session: aiohttp.ClientSession, event: Dict) -> bool:
        """Send a single event"""
        start_time = time.time()

        try:
            async with session.post(
                f'{self.api_url}/track',
                json=event,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                latency = (time.time() - start_time) * 1000  # ms

                if response.status == 200:
                    self.results['total_successful'] += 1
                    self.results['latencies'].append(latency)
                    return True
                else:
                    self.results['total_failed'] += 1
                    error_text = await response.text()
                    self.results['errors'].append(f'HTTP {response.status}: {error_text}')
                    return False

        except Exception as e:
            latency = (time.time() - start_time) * 1000
            self.results['total_failed'] += 1
            self.results['errors'].append(str(e))
            return False

    async def send_batch(self, session: aiohttp.ClientSession, events: List[Dict]) -> bool:
        """Send a batch of events"""
        start_time = time.time()

        try:
            async with session.post(
                f'{self.api_url}/track/batch',
                json={'events': events},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                latency = (time.time() - start_time) * 1000

                if response.status == 200:
                    result = await response.json()
                    self.results['total_successful'] += result.get('events_accepted', 0)
                    self.results['total_failed'] += result.get('events_rejected', 0)
                    self.results['latencies'].append(latency)
                    return True
                else:
                    self.results['total_failed'] += len(events)
                    return False

        except Exception as e:
            self.results['total_failed'] += len(events)
            self.results['errors'].append(str(e))
            return False

    async def run_load_test(
        self,
        total_events: int,
        requests_per_second: int,
        use_batch: bool = False,
        batch_size: int = 10
    ):
        """Run the load test"""
        print(f"\n{'='*60}")
        print(f"Real-Time Analytics Pipeline - Load Test")
        print(f"{'='*60}")
        print(f"Target: {total_events:,} events")
        print(f"Rate: {requests_per_second} requests/second")
        print(f"Mode: {'Batch' if use_batch else 'Single'} ({batch_size} events/batch if batch)")
        print(f"Customer ID: {self.customer_id}")
        print(f"{'='*60}\n")

        start_time = time.time()
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=100)

        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            delay = 1.0 / requests_per_second

            if use_batch:
                # Batch mode
                num_batches = total_events // batch_size
                for i in range(num_batches):
                    events = [self.generate_event() for _ in range(batch_size)]
                    task = self.send_batch(session, events)
                    tasks.append(task)
                    self.results['total_sent'] += batch_size

                    if (i + 1) % 10 == 0:
                        print(f"Queued {(i + 1) * batch_size:,}/{total_events:,} events...")

                    await asyncio.sleep(delay)
            else:
                # Single event mode
                for i in range(total_events):
                    event = self.generate_event()
                    task = self.send_event(session, event)
                    tasks.append(task)
                    self.results['total_sent'] += 1

                    if (i + 1) % 100 == 0:
                        print(f"Queued {i + 1:,}/{total_events:,} events...")

                    await asyncio.sleep(delay)

            # Wait for all tasks to complete
            print("\nWaiting for all requests to complete...")
            await asyncio.gather(*tasks)

        end_time = time.time()
        duration = end_time - start_time

        # Calculate statistics
        self.print_results(duration)

    def print_results(self, duration: float):
        """Print test results"""
        print(f"\n{'='*60}")
        print(f"Load Test Results")
        print(f"{'='*60}")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Total sent: {self.results['total_sent']:,}")
        print(f"Successful: {self.results['total_successful']:,}")
        print(f"Failed: {self.results['total_failed']:,}")
        print(f"Success rate: {(self.results['total_successful'] / self.results['total_sent'] * 100):.2f}%")

        if self.results['latencies']:
            latencies = sorted(self.results['latencies'])
            print(f"\nLatency Statistics:")
            print(f"  Min: {min(latencies):.2f}ms")
            print(f"  Max: {max(latencies):.2f}ms")
            print(f"  Mean: {sum(latencies) / len(latencies):.2f}ms")
            print(f"  p50: {latencies[len(latencies) // 2]:.2f}ms")
            print(f"  p95: {latencies[int(len(latencies) * 0.95)]:.2f}ms")
            print(f"  p99: {latencies[int(len(latencies) * 0.99)]:.2f}ms")

        actual_rps = self.results['total_sent'] / duration
        print(f"\nThroughput: {actual_rps:.2f} events/second")
        print(f"Target: <5 second end-to-end latency ✓" if duration < 5 else f"Target: <5 second end-to-end latency ✗")

        if self.results['errors']:
            print(f"\nErrors (showing first 5):")
            for error in self.results['errors'][:5]:
                print(f"  - {error}")

        print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description='Load test the analytics pipeline')
    parser.add_argument('--events', type=int, default=1000, help='Total number of events to send')
    parser.add_argument('--rps', type=int, default=100, help='Requests per second')
    parser.add_argument('--batch', action='store_true', help='Use batch API')
    parser.add_argument('--batch-size', type=int, default=10, help='Events per batch')
    parser.add_argument('--api-url', default='http://localhost:8000', help='Ingestion API URL')
    parser.add_argument('--customer-id', default='load_test', help='Customer ID')

    args = parser.parse_args()

    tester = LoadTester(api_url=args.api_url, customer_id=args.customer_id)

    asyncio.run(tester.run_load_test(
        total_events=args.events,
        requests_per_second=args.rps,
        use_batch=args.batch,
        batch_size=args.batch_size
    ))


if __name__ == '__main__':
    main()
