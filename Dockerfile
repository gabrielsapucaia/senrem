FROM python:3.11-slim

WORKDIR /app

# GDAL dependencies for rasterio
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY frontend/ frontend/

# Create data directories
RUN mkdir -p data/rasters/processed data/tiles data/vectors

EXPOSE 8000

CMD ["python", "-m", "backend.main"]
