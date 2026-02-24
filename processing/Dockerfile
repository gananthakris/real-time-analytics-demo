FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY simple_processor.py .
COPY flink_job.py .

# Run the simple processor by default
CMD ["python", "simple_processor.py"]
