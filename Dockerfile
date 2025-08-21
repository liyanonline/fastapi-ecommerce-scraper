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
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]


# # Use an official Python runtime as a parent image
# FROM python:3.12-slim

# # Set working directory
# WORKDIR /app

# # Set environment variables
# ENV PYTHONUNBUFFERED=1 \
#     PYTHONDONTWRITEBYTECODE=1 \
#     PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# # Install system dependencies
# RUN apt-get update && apt-get install -y \
#     build-essential \
#     libssl-dev \
#     libffi-dev \
#     python3-dev \
#     curl \
#     libpq-dev \
#     libjpeg-dev \
#     zlib1g-dev \
#     libpng-dev \
#     libfreetype6-dev \
#     libopenjp2-7 \
#     libtiff5-dev \
#     && rm -rf /var/lib/apt/lists/*

# # Install Playwright dependencies
# RUN pip install --no-cache-dir playwright && \
#     playwright install --with-deps chromium

# # Copy requirements file (create this separately if you don't have one)
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# # Copy application code
# COPY . .

# # Create necessary directories
# RUN mkdir -p /app/static /app/output /app/templates

# # Expose port
# EXPOSE 8000

# # Command to run the application
# CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]