# Model Training

## Current Model

The app expects a YOLO model with these classes:

- `healthy`
- `small_young`
- `yellow_stressed`
- `dead`

Path:

```text
models/palm_health.pt
```

The included model is a starter model for pipeline testing. Its confidence may be low on new orthomosaics. Treat results as review candidates until you train with your own labeled plantation imagery.

## Train With Roboflow Dataset

Set your Roboflow key in `.env`:

```text
ROBOFLOW_API_KEY=your_key_here
ROBOFLOW_MODEL_ID=oil-palm-tree-health-detection/1
```

Run:

```powershell
docker compose exec api python /scripts/setup_palm_health_model.py --epochs 50 --base-model yolov8s.pt --device 0
```

CPU-only smoke test:

```powershell
docker compose exec api python /scripts/setup_palm_health_model.py --local-yolo-dir /data/rf_train_clean --epochs 1 --imgsz 416 --batch 4 --fraction 0.12 --workers 0 --base-model yolov8n.pt --device cpu
```

## Recommended Production Dataset

Collect labels from your own UAV data:

- Original DJI photos
- Stitched orthomosaic crops
- Healthy palms
- Small/young palms
- Yellow/stressed palms
- Dead palms
- Hard negatives such as weeds, roads, houses, shadows, and bare soil

Use block-specific validation sets so accuracy reflects field reality.

## Inference Settings

`.env.example` includes:

```text
YOLO_CONFIDENCE=0.01
YOLO_IOU=0.45
```

The low confidence exists because the starter model is weak on some orthomosaic outputs. Increase this after training a stronger model.

## Quality Targets

Track these metrics during pilot testing:

- Palm count error per block
- False positives per hectare
- Missed palms per hectare
- Health class precision/recall
- Runtime per stitched layer
- Human correction time

Do not use health labels for fertilizer decisions until field validation and agronomist review are in place.
