FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy scraper code
COPY . .

# Default command — one-shot daily run
# (host cron triggers via `docker compose run --rm scraper`)
CMD ["python", "run_daily.py"]
