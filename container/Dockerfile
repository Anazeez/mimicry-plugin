FROM ubuntu:24.04

ARG MIMICRY_RENDERER_REVISION=2026-07-29-node-evidence-v7
LABEL org.opencontainers.image.revision="${MIMICRY_RENDERER_REVISION}"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-draw \
        python3 \
        python3-pip \
        python3-uno \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-ara \
        fonts-noto-core \
        fonts-noto-extra \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /service
COPY requirements.txt /service/requirements.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir -r requirements.txt

COPY app /service/container/app
COPY tests /service/container/tests
RUN touch /service/container/__init__.py

EXPOSE 8080
CMD ["python3", "-m", "container.app.server"]
