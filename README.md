# rl4phy

Geant4 muon simulation (`geant`) streaming step data over gRPC to a Python
service (`python`), which visualizes it live in [Rerun](https://rerun.io/).

## Dev mode

```
docker compose up
```

Plain `docker compose` automatically merges `docker-compose.yml` with
`docker-compose.override.yaml`. That override adds bind mounts for
`python/` and `geant4/`, so edits on your host are picked up without
rebuilding the image, plus a `stubs-generator` step that mirrors headers
and packages into `.stubs/` for your editor (see below).

- Rerun viewer: `rerun --connect rerun+http://127.0.0.1:9876/proxy`
- gRPC port `50051` is also published, e.g. for `python/test_client.py`.

## Production mode

```
docker compose -f docker-compose.yml up --build
```

This ignores the override: no bind mounts, no `.stubs/` generation, no
CMake/protoc re-run on every start. Everything is baked into the image at
build time.

## After changing Python code

Dev mode mounts `python/` into the container and reruns `server.py` on
every `up`, so:

```
docker compose restart python
```

is enough. No rebuild needed unless you changed `python/requirements.txt`
or `python/Dockerfile`, in which case:

```
docker compose build python && docker compose up -d python
```

## After changing C++ code

The `geant` service reconfigures and rebuilds with CMake on every
container start in dev mode, so a plain restart recompiles it:

```
docker compose restart geant
```

## Editor setup (IntelliSense on Windows/macOS/Linux)

Nothing to install or configure manually. `docker compose up` (dev mode)
regenerates `.stubs/` — a mirror of the container's Python packages and
C++ headers — which `pyrightconfig.json` and `.clangd` point at. This
works automatically for any dependency added later (new pip package, new
`apt-get install ...-dev`), not just the ones present today.

- If IntelliSense looks stale after adding a dependency, delete `.stubs/`
  and run `docker compose up` again to regenerate it.
- `.stubs/` is generated, gitignored, and safe to delete any time.
- Editor language servers may need a restart/reload after `.stubs/`
  changes.

## Windows

Everything above runs the same way through Docker Desktop (WSL2 backend).
No native Python/CMake/Geant4 install is needed on the host — only Docker
and your editor. `.stubs/` generation uses plain file copies (no
symlinks), so it works the same on Windows as on Linux/macOS.
