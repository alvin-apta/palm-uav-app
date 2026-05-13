from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_YAML = ROOT / "palm_health.yaml"
DEFAULT_OUTPUT_WEIGHTS = ROOT.parent / "models" / "palm_health.pt"
REQUIRED_NAMES = ["healthy", "yellow_stressed", "small_young", "dead"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the PalmOps palm-health YOLO detector locally.")
    parser.add_argument("--data", default=str(DEFAULT_DATASET_YAML), help="YOLO dataset YAML.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_WEIGHTS), help="Destination .pt used by the app.")
    parser.add_argument("--base-model", default="yolov8s.pt", help="Use yolov8s.pt or yolov8m.pt for better accuracy.")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--batch", default="auto", help="Batch size, integer or auto.")
    parser.add_argument("--device", default=None, help="Example: 0 for GPU, cpu for CPU.")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--patience", type=int, default=30)
    parser.add_argument("--project", default=str(ROOT / "runs"))
    parser.add_argument("--name", default="palm_health_local")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    data_yaml = Path(args.data).resolve()
    validate_dataset(data_yaml)
    if args.validate_only:
        print(f"Dataset is valid: {data_yaml}")
        return

    model = YOLO(args.base_model)
    train_kwargs = {
        "data": str(data_yaml),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": parse_batch(args.batch),
        "patience": args.patience,
        "project": args.project,
        "name": args.name,
        "exist_ok": True,
        "workers": args.workers,
        "plots": True,
        "cache": False,
    }
    if args.device:
        train_kwargs["device"] = args.device

    results = model.train(**train_kwargs)
    save_dir = Path(getattr(results, "save_dir", Path(args.project) / args.name))
    best = save_dir / "weights" / "best.pt"
    if not best.exists():
        raise RuntimeError(f"Training finished but best weights were not found at {best}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, output)
    validate_weights(output)
    print(f"Saved trained model to {output}")


def validate_dataset(data_yaml: Path) -> None:
    if not data_yaml.exists():
        raise FileNotFoundError(f"Missing dataset config: {data_yaml}")
    payload = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
    names = normalize_names(payload.get("names"))
    if names != REQUIRED_NAMES:
        raise ValueError(f"Dataset classes must be {REQUIRED_NAMES}; got {names}")

    dataset_root = Path(payload.get("path") or data_yaml.parent)
    if not dataset_root.is_absolute():
        dataset_root = (data_yaml.parent / dataset_root).resolve()

    for split_key in ("train", "val"):
        image_dir = dataset_root / str(payload.get(split_key, ""))
        if not image_dir.exists():
            raise FileNotFoundError(f"Missing {split_key} image directory: {image_dir}")
        label_dir = labels_dir_for(image_dir)
        if not label_dir.exists():
            raise FileNotFoundError(f"Missing {split_key} label directory: {label_dir}")
        image_count = count_images(image_dir)
        label_count = len(list(label_dir.glob("*.txt")))
        if image_count == 0:
            raise ValueError(f"No images found in {image_dir}")
        if label_count == 0:
            raise ValueError(f"No YOLO label files found in {label_dir}")
        validate_label_files(label_dir)
        print(f"{split_key}: {image_count} images, {label_count} labels")


def normalize_names(raw_names: object) -> list[str]:
    if isinstance(raw_names, dict):
        return [str(raw_names[index]) for index in sorted(raw_names)]
    if isinstance(raw_names, list):
        return [str(name) for name in raw_names]
    return []


def labels_dir_for(image_dir: Path) -> Path:
    parts = list(image_dir.parts)
    if "images" in parts:
        index = len(parts) - 1 - parts[::-1].index("images")
        parts[index] = "labels"
        return Path(*parts)
    return image_dir.parent.parent / "labels" / image_dir.name


def count_images(image_dir: Path) -> int:
    suffixes = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    return sum(1 for path in image_dir.rglob("*") if path.suffix.lower() in suffixes)


def validate_label_files(label_dir: Path) -> None:
    for label_path in label_dir.glob("*.txt"):
        for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) != 5:
                raise ValueError(f"{label_path}:{line_number} must have 5 YOLO values")
            class_id = int(float(parts[0]))
            if class_id < 0 or class_id >= len(REQUIRED_NAMES):
                raise ValueError(f"{label_path}:{line_number} class id {class_id} is outside 0-3")
            for value in parts[1:]:
                parsed = float(value)
                if parsed < 0 or parsed > 1:
                    raise ValueError(f"{label_path}:{line_number} coordinate {parsed} is outside 0-1")


def validate_weights(path: Path) -> None:
    model = YOLO(str(path))
    names = normalize_names(model.names)
    if names != REQUIRED_NAMES:
        raise ValueError(f"Trained model classes must be {REQUIRED_NAMES}; got {names}")


def parse_batch(value: str) -> int | float:
    normalized = str(value).strip().lower()
    if normalized == "auto":
        return -1
    if "." in normalized:
        return float(normalized)
    return int(normalized)


if __name__ == "__main__":
    main()
