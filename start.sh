#!/bin/bash

# Quick Start Script for Real-Time Analytics Pipeline
# Starts all services in the correct order

set -e

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  Real-Time Analytics Pipeline - Quick Start                   ║"
echo "║  Beat Claude Challenge - Engineer 004                         ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Creating from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env and add your ANTHROPIC_API_KEY"
    echo ""
fi

# Source environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Step 1: Start infrastructure
echo "🚀 Step 1: Starting infrastructure (Kafka, ClickHouse, Redis, Prometheus)..."
docker-compose up -d

echo "⏳ Waiting for services to be ready (30 seconds)..."
sleep 30

# Check service health
echo "🔍 Checking service health..."

# Check Kafka
if docker-compose exec -T kafka kafka-broker-api-versions --bootstrap-server localhost:9092 > /dev/null 2>&1; then
    echo "  ✅ Kafka is ready"
else
    echo "  ⚠️  Kafka not ready yet, continuing anyway..."
fi

# Check ClickHouse
if docker-compose exec -T clickhouse clickhouse-client --query "SELECT 1" > /dev/null 2>&1; then
    echo "  ✅ ClickHouse is ready"
else
    echo "  ⚠️  ClickHouse not ready yet, continuing anyway..."
fi

# Check Redis
if docker-compose exec -T redis redis-cli ping > /dev/null 2>&1; then
    echo "  ✅ Redis is ready"
else
    echo "  ⚠️  Redis not ready yet, continuing anyway..."
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  Infrastructure Ready!                                         ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 Services available at:"
echo "  • Kafka: localhost:9092"
echo "  • ClickHouse: localhost:8123 (HTTP), localhost:9000 (Native)"
echo "  • Redis: localhost:6379"
echo "  • Prometheus: http://localhost:9090"
echo "  • Grafana: http://localhost:3000 (admin/admin)"
echo ""
echo "To check logs: docker-compose logs -f [service-name]"
echo ""

# Step 2: Instructions for starting application services
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  Next Steps - Start Application Services                      ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "Open 4 separate terminal windows and run:"
echo ""
echo "Terminal 1 - Ingestion API:"
echo "  cd ingestion"
echo "  pip install -r requirements.txt"
echo "  uvicorn app:app --host 0.0.0.0 --port 8000"
echo ""
echo "Terminal 2 - Stream Processor:"
echo "  cd processing"
echo "  pip install -r requirements.txt"
echo "  python simple_processor.py"
echo ""
echo "Terminal 3 - Analytics API (AI-powered!):"
echo "  cd analytics-api"
echo "  export ANTHROPIC_API_KEY=your_key_here"
echo "  pip install -r requirements.txt"
echo "  uvicorn app:app --host 0.0.0.0 --port 8001"
echo ""
echo "Terminal 4 - Dashboard:"
echo "  cd dashboard"
echo "  npm install"
echo "  npm run dev"
echo ""
echo "Then open: http://localhost:5173"
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  Optional: Test the Pipeline                                  ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "SDK Demo (JavaScript):"
echo "  Open: sdk/demo.html in your browser"
echo ""
echo "Load Test:"
echo "  pip install aiohttp"
echo "  python load_test.py --events 1000 --rps 100"
echo ""
echo "Manual Event:"
echo "  curl -X POST http://localhost:8000/track \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"customer_id\":\"demo_tenant\",\"visitor_id\":\"test_123\",\"session_id\":\"session_456\",\"event_type\":\"page_view\",\"event_name\":\"Test\",\"properties\":{}}'"
echo ""
echo "Query ClickHouse:"
echo "  docker-compose exec clickhouse clickhouse-client --query 'SELECT count(*) FROM events_raw'"
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║  Ready to Beat Claude! 🏆                                      ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
