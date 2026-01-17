FROM ghcr.io/astral-sh/uv:python3.13-trixie

WORKDIR /app

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y build-essential python3-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY . /app/

RUN uv sync

CMD ["uv", "run", "python", "-m", "uf"]
