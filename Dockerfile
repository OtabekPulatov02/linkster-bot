FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg nodejs ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY bot.py entrypoint.sh ./
RUN chmod +x entrypoint.sh && useradd -m bot && mkdir -p /data && chown bot /data
USER bot
ENV WORKDIR=/data
EXPOSE 10000
CMD ["./entrypoint.sh"]
