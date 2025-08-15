FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENV PORT=8080
CMD ["sh","-c","gunicorn -w 1 -k gthread -t 120 -b 0.0.0.0:${PORT} app:app"]
