# Sentinel Brain - ML Inference Server
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY pyproject.toml .

# Install Python dependencies
RUN pip install --no-cache-dir pip --upgrade && \
    pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-ansi

# Copy application code
COPY src/ ./src/
COPY proto/ ./proto/
COPY models/ ./models/

# Generate gRPC code
RUN python -m grpc_tools.protoc -I./proto \
    --python_out=./src/sentinel_brain/grpc \
    --grpc_python_out=./src/sentinel_brain/grpc \
    proto/sentinel.proto

# Set Python path
ENV PYTHONPATH=/app/src

# Expose gRPC port
EXPOSE 50051

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import grpc; ch = grpc.insecure_channel('localhost:50051'); grpc.channel_ready_future(ch).result(timeout=5)"

# Run server
CMD ["python", "-m", "sentinel_brain.grpc.server", "--host", "0.0.0.0", "--port", "50051"]
