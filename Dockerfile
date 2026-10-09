# Image de la plateforme : moteur crc + application Django
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp1 : requis par LightGBM
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install -r requirements.txt && pip install -e .
COPY webapp ./webapp
COPY sql ./sql

# Utilisateur non privilegie
RUN useradd --create-home --uid 1000 crc && mkdir -p data models outputs staticfiles \
    && chown -R crc:crc /app
USER crc

EXPOSE 8000
CMD ["gunicorn", "--pythonpath", "webapp", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", "--timeout", "300"]
