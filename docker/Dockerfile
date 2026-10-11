# Production Container for PS 26250
# Air Power — Dynamic Air Operations & Resource Optimisation
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONPATH=. \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies including coinor-cbc solver and curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    coinor-cbc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code and static assets
COPY backend ./backend
COPY frontend ./frontend
COPY seed_database.py .

# Expose port (default 8000, dynamically overridden by $PORT on Render)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Seed database and start uvicorn
CMD ["sh", "-c", "python seed_database.py && python -m uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
