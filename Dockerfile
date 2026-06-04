ARG BASE_IMAGE=kasta03/geant4-base:11.3.2
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    libexpat1 \
    libxerces-c3.2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/geant
COPY geant/ /app/geant/
RUN cmake -S /app/geant -B /app/geant/build \
    -DGeant4_DIR=/opt/geant4/lib/cmake/Geant4 \
    -DCMAKE_BUILD_TYPE=Release && \
    cmake --build /app/geant/build --config Release --parallel $(nproc) && \
    install -m 0755 /app/geant/build/rl4phy-geant /usr/local/bin/rl4phy-geant

COPY geant/macros /work/macros

WORKDIR /work
VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/rl4phy-geant"]
CMD ["macros/run.mac"]
