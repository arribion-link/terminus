FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm@sha256:7662249c0db9db96efc80fa8e0e5b8f4ec9bdf43b5d820b8a271e28f74b98b42

RUN apt-get update \
    && apt-get install -y --no-install-recommends tmux asciinema coreutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY data/ /app/data/

RUN python3 -c "import hashlib, os, subprocess"
