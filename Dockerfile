ARG BASE_IMAGE=kasta03/geant4-base:11.3.2
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    libexpat1 \
    libxerces-c3.2 \
    libgrpc++1 \
    libprotobuf23 \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y \
    libgrpc++-dev \
    libgrpc-dev \
    libprotobuf-dev \
    protobuf-compiler \
    protobuf-compiler-grpc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/geant4/MUonE
COPY proto/ /app/proto/
COPY geant4/ /app/geant4/
RUN cmake -S /app/geant4/MUonE -B /app/geant4/MUonE/build \
    -DGeant4_DIR=/opt/geant4/lib/cmake/Geant4 \
    -DCMAKE_BUILD_TYPE=Release && \
    cmake --build /app/geant4/MUonE/build --config Release --parallel $(nproc) && \
    install -m 0755 /app/geant4/MUonE/build/rl4phy-geant /usr/local/bin/rl4phy-geant

COPY geant4/MUonE/macros /work/macros
COPY geant4/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /work
VOLUME ["/data", "/export"]
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["--grpc-host", "python:50051", "macros/run.mac"]
