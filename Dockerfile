FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    OUT_DIR=/app/data \
    DB_DIR=/app/data

# Install system libraries for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create persistent data directory
RUN mkdir -p /app/data && chmod 777 /app/data

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright headless browser
RUN playwright install chromium
RUN playwright install-deps chromium || true

# Copy application source code
COPY . .

# Railway injects PORT at runtime — expose it
EXPOSE 8080

# Run LeadsOSINT (reads PORT from env, defaults to 5050)
CMD ["python", "app.py"]
