FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --uid 10001 --user-group --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin sandbox \
    && find / -xdev -perm /6000 -type f -exec chmod a-s {} + \
    && rm -rf /var/lib/apt/lists/* /root/.cache

USER 10001:10001
WORKDIR /tmp

ENTRYPOINT ["python", "-I", "-"]
