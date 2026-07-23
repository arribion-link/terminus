# TODO(author): the digest below is a PLACEHOLDER. Resolve the real digest for
# python:3.13-slim-bookworm (e.g. `docker pull ... && docker inspect --format
# '{{index .RepoDigests 0}}'`) and replace it before submitting -- CI's
# check_pinned_images gate will reject an unresolved/placeholder digest.
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:0000000000000000000000000000000000000000000000000000000000000000

WORKDIR /app

# System packages: perl + git for the inference worker and model repo, plus
# tmux/asciinema required by the agent runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema \
        ca-certificates \
        curl \
        git \
        perl \
        tmux \
    && rm -rf /var/lib/apt/lists/*

# Application + verifier dependencies (pinned).
RUN pip install --no-cache-dir \
        flask==3.0.3 \
        polars==1.9.0 \
        pytest==8.3.3 \
        pytest-json-ctrf==0.3.3 \
        requests==2.32.3

# Task files (solution/ and tests/ are intentionally never copied here).
COPY app/ /app/

# Build-time steps: generate the feature contract from the Polars reference
# script, then deterministically construct the local bare model repo and its
# ref-pinning lockfile.
RUN python3 /app/contract/build_contract.py \
    && bash /app/model_src/build_model_repo.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 8080
