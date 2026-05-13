# Palm Health YOLO Training

This folder is the honest model creation path for `palm_health.pt`.

## Dataset Layout

Put labeled YOLO detection data here:

```text
model_training/datasets/palm_health/
  images/train/
  images/val/
  labels/train/
  labels/val/
```

Each label file must use YOLO format:

```text
class_id x_center y_center width height
```

All coordinates are normalized from `0` to `1`.

## Classes

```text
0 healthy
1 yellow_stressed
2 small_young
3 dead
```

## Training

Validate the local labeled dataset:

```powershell
docker compose exec api python /workspace/model_training/train_palm_health.py --validate-only
```

Train locally and replace the app model:

```powershell
docker compose exec api python /workspace/model_training/train_palm_health.py --base-model yolov8s.pt --epochs 120 --imgsz 960 --batch auto --device 0
```

For CPU-only training, use a smaller run:

```powershell
docker compose exec api python /workspace/model_training/train_palm_health.py --base-model yolov8n.pt --epochs 30 --imgsz 640 --batch 4 --device cpu
```

The script writes:

```text
models/palm_health.pt
```

That file is mounted into the Docker worker at:

```text
/models/palm_health.pt
```

## Important

The app intentionally does not create fake model weights. If `models/palm_health.pt` is missing, inference jobs fail with `model_not_configured`.
