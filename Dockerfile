FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BHASHINI_CONF=/app/config/bhashini.conf BHASHINI_DATA=/app/data
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ server/
COPY web/ web/
RUN useradd --uid 1000 --create-home kit && mkdir -p config data && chown kit config data
USER kit

EXPOSE 8765 8766
# Default: the HTTP service. docker-compose.yml overrides this for the streaming service.
CMD ["uvicorn", "app:app", "--app-dir", "server", "--host", "0.0.0.0", "--port", "8765"]
