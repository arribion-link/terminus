FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:REPLACE_WITH_ACTUAL_DIGEST

# System dependencies - tmux and asciinema are REQUIRED
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tmux \
        asciinema \
        git \
        perl \
        libjson-perl \
        libfile-slurp-perl \
        liblist-util-perl \
        libipc-run-perl \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies - pinned versions
RUN pip install --no-cache-dir \
    flask==3.0.3 \
    polars==1.7.1 \
    numpy==1.26.4 \
    pytest==8.3.3 \
    gitpython==3.1.43 \
    pytest-ctrf==0.3.0

COPY app/ /app/

ENV PYTHONPATH=/app
ENV PERL5LIB=/app/perl_worker/lib

EXPOSE 5000