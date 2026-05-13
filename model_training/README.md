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

Run inside an environment with `ultralytics` installed:

```powershell
python model_training/train_palm_health.py
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

