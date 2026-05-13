# Setup Guide

## Requirements

- Docker Desktop
- Git
- Modern browser
- 16 GB RAM minimum for small stitching jobs, 32 GB preferred for larger UAV datasets

## First Run

```powershell
git clone https://github.com/alvin-apta/palm-uav-app.git
cd palm-uav-app
Copy-Item .env.example .env
docker compose up --build
```

The API seeds a default owner account on startup:

```text
owner@example.com
palmops123
```

## Services

| Service | URL |
| --- | --- |
| Frontend | http://localhost:5173 |
| API | http://localhost:8090 |
| API docs | http://localhost:8090/docs |
| TiTiler | http://localhost:8082 |
| NodeODM | http://localhost:3000 |
| PostgreSQL | localhost:5433 |
| Redis | localhost:6380 |

## Environment

Copy `.env.example` to `.env` and edit local-only values there. Never commit `.env`.

Important values:

- `SECRET_KEY`: change before production use.
- `MODEL_WEIGHTS_PATH`: defaults to `/models/palm_health.pt`.
- `YOLO_CONFIDENCE`: low default is used for reviewable candidate boxes with the starter model.
- `NODEODM_URL`: defaults to the Compose `nodeodm` service.
- `PUBLIC_API_BASE_URL`: browser-facing API URL.
- `PUBLIC_TITILER_BASE_URL`: browser-facing TiTiler URL.

## Start And Stop

```powershell
docker compose up --build
docker compose down
```

To keep database volumes:

```powershell
docker compose down
```

To reset database volumes completely:

```powershell
docker compose down -v
```

## Verification

```powershell
docker compose ps
docker compose exec api pytest
docker compose exec frontend npm run build
```
