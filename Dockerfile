FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1

ARG APP_UID=1000
ARG APP_GID=1000

RUN groupadd --gid "${APP_GID}" django     && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home django     && mkdir -p /app /data     && chown django:django /app /data

WORKDIR /app

COPY req.txt /tmp/req.txt
RUN python -m pip install -r /tmp/req.txt

COPY --chown=django:django . /app

USER django

EXPOSE 8000

ENTRYPOINT ["python", "/app/docker_bootstrap.py"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
