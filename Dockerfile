FROM ghcr.io/astral-sh/uv:debian-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV LANG=en_US.UTF-8
ENV PATH="/app/.venv/bin:$PATH"

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        bash \
        git \
        curl \
        ca-certificates \
        locales && \
    locale-gen en_US.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# Sanal ortamı oluştur ve requirements.txt’i yükle
RUN python -m venv .venv
RUN .venv/bin/pip install --upgrade pip
RUN .venv/bin/pip install -r requirements.txt

RUN chmod +x start.sh
CMD ["bash", "start.sh"]
