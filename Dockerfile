# Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Paquetes mínimos
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Dependencias
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Código
COPY . .

# Puerto por defecto (Railway te inyecta $PORT)
ENV PORT=5000
EXPOSE 5000

# **IMPORTANTE: solo un CMD**. Aquí sí se expande ${PORT}.
CMD ["sh","-c","gunicorn -w 2 -k gthread -t 120 -b 0.0.0.0:${PORT:-5000} app:app"]
