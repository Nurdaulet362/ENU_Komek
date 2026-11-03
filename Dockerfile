FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 ENU_HOSTED=1 PORT=10000 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 enu
COPY app/ ./app/
COPY web/ ./web/
COPY server.py ./
USER enu
EXPOSE 10000
CMD ["python", "server.py", "--host", "0.0.0.0"]
