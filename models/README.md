# Palm Health Model Weights

Place the trained YOLO palm-health model here:

```text
palm_health.pt
```

The production inference worker expects this path inside Docker:

```text
/models/palm_health.pt
```

Required classes:

- `healthy`
- `yellow_stressed`
- `small_young`
- `dead`

Do not place a generic COCO YOLO model here for production health inference. A generic model does not know palm-health classes and the worker will reject it.

## Create The Model

Use the included setup script with a Roboflow API key. It downloads the public Oil palm tree Health detection dataset, remaps the classes to the app schema, trains YOLO locally, and copies the best weights here:

```bash
docker compose exec api python /scripts/setup_palm_health_model.py --epochs 50 --base-model yolov8s.pt --device 0
```

For CPU-only testing, use fewer epochs, a smaller image size, and a dataset fraction:

```bash
docker compose exec api python /scripts/setup_palm_health_model.py --local-yolo-dir /data/rf_train_clean --epochs 1 --imgsz 416 --batch 4 --fraction 0.12 --workers 0 --base-model yolov8n.pt --device cpu
```

The Roboflow dataset currently exports labels as `healthy`, `immature`, `stressed`, and `unhealthy`; the setup script maps them to `healthy`, `small_young`, `yellow_stressed`, and `dead`. Treat `dead` from this starter dataset as a severe/unhealthy bucket until you add field-labeled dead palms.

## Hosted Fallback

Instead of a local `.pt`, you can set these in `.env`:

```text
ROBOFLOW_API_KEY=YOUR_KEY
ROBOFLOW_MODEL_ID=oil-palm-tree-health-detection/1
```

The worker will then use the hosted Roboflow model when `/models/palm_health.pt` is missing.
