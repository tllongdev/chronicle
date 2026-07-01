FROM python:3.12-slim

# Install uv for fast, reproducible dependency resolution.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .

# The store and rendered graph live under /app so they can be mounted out.
RUN mkdir -p /app/output

ENTRYPOINT ["chronicle"]
