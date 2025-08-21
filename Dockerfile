FROM python:3.11-slim

# Install system dependencies for Playwright and Matplotlib
RUN apt-get update && apt-get install -y \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-liberation libappindicator3-1 libnspr4 libxss1 \
    && apt-get clean

WORKDIR /usr/src/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
RUN mkdir -p /usr/src/app/output && chmod -R 777 /usr/src/app/output
COPY . .
CMD ["uvicorn", "app_fastapi:app", "--host", "0.0.0.0", "--port", "8000"]

