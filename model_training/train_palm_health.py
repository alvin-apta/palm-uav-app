from __future__ import annotations

from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
DATASET_YAML = ROOT / "palm_health.yaml"
OUTPUT_WEIGHTS = ROOT.parent / "models" / "palm_health.pt"


def main() -> None:
    if not DATASET_YAML.exists():
        raise FileNotFoundError(f"Missing dataset config: {DATASET_YAML}")

    model = YOLO("yolov8n.pt")
    results = model.train(
        data=str(DATASET_YAML),
        epochs=80,
        imgsz=1024,
        batch=8,
        patience=20,
        project=str(ROOT / "runs"),
        name="palm_health_yolov8n",
        exist_ok=True,
    )
    best = Path(results.save_dir) / "weights" / "best.pt"
    if not best.exists():
        raise RuntimeError(f"Training finished but best weights were not found at {best}")
    OUTPUT_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_WEIGHTS.write_bytes(best.read_bytes())
    print(f"Saved trained model to {OUTPUT_WEIGHTS}")


if __name__ == "__main__":
    main()

