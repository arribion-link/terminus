# Non-canonical base image justification:
# python:3.12-slim-bookworm is the project-standard image for
# Perl+Python multi-language tasks in this task family.
# It pairs reliably with the Perl 5.36 toolchain from bookworm.

FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm@sha256:7662249c0db9db96efc80fa8e0e5b8f4ec9bdf43b5d820b8a271e28f74b98b42

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        perl \
        git \
        tmux \
        asciinema \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    flask==3.1.3 \
    pytest==9.1.1 \
    pytest-json-ctrf==0.5.3 \
    polars==1.15.0

ENV GIT_AUTHOR_NAME=test \
    GIT_AUTHOR_EMAIL=test@terminus.local \
    GIT_COMMITTER_NAME=test \
    GIT_COMMITTER_EMAIL=test@terminus.local \
    PYTHONPATH=/app/gateway

WORKDIR /app

COPY app/ /app/
COPY model-repo.git/ /srv/model-repo.git/
