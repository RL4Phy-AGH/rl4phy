FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

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
