FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip setuptools wheel

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY credentials.json .
COPY .env .

# สร้าง directory สำหรับ volume
RUN mkdir -p /app/data

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Mount point สำหรับ database
VOLUME ["/app/data"]

EXPOSE 8000
CMD ["python", "main.py"]
