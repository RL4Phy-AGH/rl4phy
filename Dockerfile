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

WORKDIR /app
COPY proto/ /app/proto/
COPY geant4/ /app/geant4/

RUN cmake -S /app/geant4/MUonE -B /app/geant4/MUonE/build \
    -DGeant4_DIR=/opt/geant4/lib/cmake/Geant4 \
    -DCMAKE_BUILD_TYPE=Release && \
    cmake --build /app/geant4/MUonE/build --config Release --parallel $(nproc) && \
    install -m 0755 /app/geant4/MUonE/build/rl4phy-geant /usr/local/bin/rl4phy-geant

RUN cmake -S /app/geant4/G4Examples -B /app/geant4/G4Examples/build \
    -DGeant4_DIR=/opt/geant4/lib/cmake/Geant4 \
    -DCMAKE_BUILD_TYPE=Release \
    -DWITH_GEANT4_UIVIS=OFF && \
    cmake --build /app/geant4/G4Examples/build --config Release --parallel $(nproc) && \
    install -m 0755 /app/geant4/G4Examples/build/B1_rl4phys /usr/local/bin/B1_rl4phys

COPY geant4/MUonE/macros /work/macros
COPY geant4/G4Examples/B1/run1.mac geant4/G4Examples/B1/run2.mac /work/B1/
COPY geant4/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /work
VOLUME ["/data", "/export"]
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["--grpc-host", "python:50051", "macros/run.mac"]
