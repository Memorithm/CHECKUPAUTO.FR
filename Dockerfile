# Pinned by digest (multi-arch index of python:3.12-slim, 2026-10-10); refresh
# deliberately with `docker buildx imagetools inspect python:3.12-slim` (audit O-03).
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CYBERCHECK_BIND_HOST=0.0.0.0 \
    CYBERCHECK_BIND_PORT=8765 \
    CYBERCHECK_DATA_DIR=/var/lib/checkupauto/data \
    CYBERCHECK_PRIVATE_DIR=/var/lib/checkupauto/private \
    CYBERCHECK_SECURITY_DIR=/var/lib/checkupauto/security \
    CYBERCHECK_INTEGRITY_DIR=/var/lib/checkupauto/integrity

RUN groupadd --gid 10001 cybercheck \
 && useradd --uid 10001 --gid 10001 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin cybercheck

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      poppler-utils \
      tesseract-ocr \
      tesseract-ocr-eng \
      tesseract-ocr-fra \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1 \
 && python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=cybercheck:cybercheck . /app

USER cybercheck:cybercheck

EXPOSE 8765

HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/', timeout=3).read(1)" || exit 1

CMD ["python", "admin_server.py"]
