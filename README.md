# Palm UAV App

Full-stack Web-GIS application for palm oil plantation monitoring from UAV imagery.

The app lets a user upload DJI drone photos, stitch them into orthomosaic map layers, run queued palm-health inference on stitched maps, review bounding boxes on MapLibre, count unique palms, and export field/prescription outputs.

## Stack

- FastAPI backend
- PostgreSQL + PostGIS
- Redis + ARQ worker queue
- Vite React frontend
- MapLibre GL JS
- TiTiler-compatible COG raster streaming
- NodeODM/OpenDroneMap service for stitching
- Ultralytics YOLO palm-health model

## Quick Start

Prerequisites:

- Docker Desktop
- Git
- At least 16 GB RAM recommended for stitching

Clone and start:

```powershell
git clone https://github.com/alvin-apta/palm-uav-app.git
cd palm-uav-app
Copy-Item .env.example .env
docker compose up --build
```

Open:

- App: http://localhost:5173
- API docs: http://localhost:8090/docs
- TiTiler docs: http://localhost:8082/api.html
- NodeODM: http://localhost:3000

Default login:

```text
owner@example.com
palmops123
```

## Main Workflow

1. Open **Missions** and create/select an estate block.
2. Open **Upload Imagery** and upload original DJI photos.
3. Open **Stitching** and create a low-memory stitch job.
4. Preview the stitched orthomosaic and open it on the map.
5. Open **Map**, select overlay layers, and run AI inference.
6. Review palm bounding boxes by class.
7. Use **Prescriptions** and **Reports** for exports.

Inference intentionally runs on stitched orthomosaic/COG layers, not raw photos. This keeps the review map aligned and lets detection boxes cascade from selected overlays.

## Important Folders

```text
backend/          FastAPI, workers, database models, tests
frontend/         Vite React + MapLibre UI
scripts/          Model setup and utility scripts
models/           Local YOLO model location
model_training/   Training scaffold
docs/             Product and operations documentation
data/             Runtime uploads, ODM projects, exports (ignored by Git)
```

## Model Weights

The app expects the local model at:

```text
models/palm_health.pt
```

Inside Docker this is mounted as:

```text
/models/palm_health.pt
```

Required classes:

- `healthy`
- `small_young`
- `yellow_stressed`
- `dead`

The included starter model is suitable for testing the pipeline. For production accuracy, retrain with plantation-specific aerial labels.

## Documentation

- [Setup Guide](docs/SETUP.md)
- [User Guide](docs/USER_GUIDE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Operations](docs/OPERATIONS.md)
- [Model Training](docs/MODEL_TRAINING.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## Useful Commands

```powershell
docker compose up --build
docker compose ps
docker compose logs --tail=120 api
docker compose logs --tail=120 worker
docker compose restart api worker frontend
docker compose exec api pytest
docker compose exec frontend npm run build
```

## Notes

- Do not commit `.env`, uploaded imagery, ODM projects, database volumes, or large training datasets.
- COG and image outputs are stored under `data/` and are ignored by Git.
- Mini 5 Pro RGB imagery supports palm counting, missing-palm review, canopy size proxy, and visual health attention zones. It does not replace multispectral/soil sampling for true fertilizer prescriptions.
