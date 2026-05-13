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

## Train With Local Labels

Create or export a YOLO detection dataset:

```text
model_training/datasets/palm_health/
  images/train/
  images/val/
  labels/train/
  labels/val/
```

Use the app class order exactly:

```text
0 healthy
1 yellow_stressed
2 small_young
3 dead
```

Validate the dataset before training:

```powershell
docker compose exec api python /workspace/model_training/train_palm_health.py --validate-only
```

Train a stronger local model and replace `models/palm_health.pt`:

```powershell
docker compose exec api python /workspace/model_training/train_palm_health.py --base-model yolov8s.pt --epochs 120 --imgsz 960 --batch auto --device 0
```

CPU-only fallback:

```powershell
docker compose exec api python /workspace/model_training/train_palm_health.py --base-model yolov8n.pt --epochs 30 --imgsz 640 --batch 4 --device cpu
```

Restart inference services after training:

```powershell
docker compose restart api worker
```

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
YOLO_CONFIDENCE=0.25
YOLO_IOU=0.45
```

Use `0.25` as the starting threshold for a usable model. Lower it only if the model misses many palms; raise it if the map shows too many false positives.

## Quality Targets

Track these metrics during pilot testing:

- Palm count error per block
- False positives per hectare
- Missed palms per hectare
- Health class precision/recall
- Runtime per stitched layer
- Human correction time

Do not use health labels for fertilizer decisions until field validation and agronomist review are in place.
