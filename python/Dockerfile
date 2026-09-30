FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.8 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/python/.venv \
    PATH=/app/python/.venv/bin:$PATH

# pyg4ometry links against OpenGL/X11 even headless (OpenCascade + VTK).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libgl1 \
       libglu1-mesa \
       libxrender1 \
       libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/python

# Dependencies first, so a source-only change does not re-resolve the lock.
COPY python/pyproject.toml python/uv.lock python/.python-version ./
RUN uv sync --frozen --no-dev

COPY proto/ /app/proto/
COPY python/ /app/python/

RUN python -m grpc_tools.protoc \
    -I/app/proto \
    --python_out=/app/python \
    --grpc_python_out=/app/python \
    /app/proto/rl4phy.proto

EXPOSE 50051
CMD ["python", "server.py"]
