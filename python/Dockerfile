FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# pyg4ometry links against OpenGL/X11 even headless (OpenCascade + VTK).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libgl1 \
       libglu1-mesa \
       libxrender1 \
       libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY python/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/ /app/proto/
COPY python/ /app/python/

WORKDIR /app/python
RUN python -m grpc_tools.protoc \
    -I/app/proto \
    --python_out=/app/python \
    --grpc_python_out=/app/python \
    /app/proto/rl4phy.proto

EXPOSE 50051
CMD ["python", "server.py"]
