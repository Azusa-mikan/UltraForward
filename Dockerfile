FROM ghcr.io/astral-sh/uv:python3.13-trixie 

WORKDIR /app

COPY . /app/

RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y build-essential python3-dev && \
    uv sync && \
    apt-get remove -y build-essential python3-dev --purge && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

CMD ["uv", "run", "python", "-m", "uf"]
