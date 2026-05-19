from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


WORKSPACE = "oil-palm-health-detection"
PROJECT = "oil-palm-tree-health-detection"
VERSION = 1
TARGET_NAMES = ["healthy", "yellow_stressed", "small_young", "dead"]
CLASS_MAP = {
    "healthy": "healthy",
    "healthy_palm": "healthy",
    "yellow": "yellow_stressed",
    "yellowish": "yellow_stressed",
    "yellowish_palm": "yellow_stressed",
    "yellow_stressed": "yellow_stressed",
    "small": "small_young",
    "smallish": "small_young",
    "smallish_palm": "small_young",
    "small_young": "small_young",
    "immature": "small_young",
    "stressed": "yellow_stressed",
    "dead": "dead",
    "dead_palm": "dead",
    # The Roboflow Universe dataset exposes "unhealthy" but not a literal "dead"
    # label. Use it as the app's severe/dead bucket for local starter training.
    "unhealthy": "dead",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the oil-palm health dataset and train YOLO weights.")
    parser.add_argument("--roboflow-api-key", default=os.getenv("ROBOFLOW_API_KEY"), help="Roboflow API key with Universe dataset access.")
    parser.add_argument("--dataset-dir", default="/data/palm_health_dataset", help="Where the Roboflow dataset should be stored.")
    parser.add_argument("--local-yolo-dir", default="", help="Existing YOLO dataset folder with data.yaml and train/valid labels.")
    parser.add_argument("--local-coco-dir", default="", help="Existing MOPAD-style COCO folder with train2017, val2017, and annotations.")
    parser.add_argument("--converted-dir", default="/data/palm_health_yolo", help="Output folder for converted COCO-to-YOLO data.")
    parser.add_argument("--output", default="/models/palm_health.pt", help="Final YOLO .pt path used by PalmOps.")
    parser.add_argument("--base-model", default="yolov8n.pt", help="Ultralytics base model. Use yolov8s.pt for better accuracy.")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=parse_batch, default=-1)
    parser.add_argument("--device", default=None, help="Example: 0 for GPU, cpu for CPU.")
    parser.add_argument("--fraction", type=float, default=1.0, help="Fraction of the training dataset to use.")
    parser.add_argument("--workers", type=int, default=0, help="Dataloader workers. Use 0 on small Docker desktops.")
    parser.add_argument("--train-project", default="/data/model_runs")
    parser.add_argument("--train-name", default="palm_health_yolo")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()

    if args.local_yolo_dir:
        data_yaml = remap_dataset(Path(args.local_yolo_dir))
    elif args.local_coco_dir:
        data_yaml = convert_coco_to_yolo(Path(args.local_coco_dir), Path(args.converted_dir))
    else:
        if not args.roboflow_api_key:
            raise SystemExit(
                "Provide --roboflow-api-key, set ROBOFLOW_API_KEY, or use --local-coco-dir /data/mopad_site2."
            )
        dataset_dir = download_dataset(args.roboflow_api_key, Path(args.dataset_dir))
        data_yaml = remap_dataset(dataset_dir)
    print(f"Prepared 4-class dataset: {data_yaml}")
    if args.download_only:
        return
    best_weights = train_yolo(args, data_yaml)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best_weights, output)
    validate_weights(output)
    print(f"Palm health YOLO model saved to {output}")


def download_dataset(api_key: str, dataset_dir: Path) -> Path:
    try:
        from roboflow import Roboflow
    except ImportError as exc:
        raise SystemExit("Install Roboflow first: pip install roboflow") from exc

    dataset_dir.parent.mkdir(parents=True, exist_ok=True)
    rf = Roboflow(api_key=api_key)
    project = rf.workspace(WORKSPACE).project(PROJECT)
    version = project.version(VERSION)
    dataset = version.download("yolov8", location=str(dataset_dir), overwrite=True)
    return Path(dataset.location)


def remap_dataset(dataset_dir: Path) -> Path:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Install PyYAML first: pip install pyyaml") from exc

    data_yaml = dataset_dir / "data.yaml"
    remapped_yaml = dataset_dir / "palm_health_data.yaml"
    marker = dataset_dir / ".palmops_remapped"
    if marker.exists() and remapped_yaml.exists():
        print(f"Dataset already remapped: {remapped_yaml}")
        return remapped_yaml

    with data_yaml.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    source_names = data.get("names") or []
    if isinstance(source_names, dict):
        source_names = [source_names[index] for index in sorted(source_names)]
    source_to_target: dict[int, int] = {}
    for index, name in enumerate(source_names):
        normalized = str(name).strip().lower().replace(" ", "_").replace("-", "_")
        target_name = CLASS_MAP.get(normalized)
        if target_name:
            source_to_target[index] = TARGET_NAMES.index(target_name)

    if len(set(source_to_target.values())) < len(TARGET_NAMES):
        raise SystemExit(
            f"Dataset class names do not include all required classes. Found names: {source_names}; "
            f"mapped indexes: {source_to_target}"
        )

    for split in ("train", "valid", "test"):
        labels_dir = dataset_dir / split / "labels"
        if not labels_dir.exists():
            continue
        for label_path in labels_dir.glob("*.txt"):
            kept_lines = []
            for line in label_path.read_text(encoding="utf-8").splitlines():
                parts = line.strip().split()
                if len(parts) < 5:
                    continue
                try:
                    source_class = int(float(parts[0]))
                except ValueError:
                    continue
                target_class = source_to_target.get(source_class)
                if target_class is None:
                    continue
                kept_lines.append(" ".join([str(target_class), *parts[1:]]))
            label_path.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")

    remapped = {
        "path": str(dataset_dir),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": len(TARGET_NAMES),
        "names": TARGET_NAMES,
    }
    remapped_yaml.write_text(yaml.safe_dump(remapped, sort_keys=False), encoding="utf-8")
    marker.write_text(
        json.dumps({"source_names": source_names, "target_names": TARGET_NAMES}, indent=2),
        encoding="utf-8",
    )
    return remapped_yaml


def convert_coco_to_yolo(coco_dir: Path, output_dir: Path) -> Path:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Install PyYAML first: pip install pyyaml") from exc

    train_json = coco_dir / "annotations" / "instances_train2017.json"
    val_json = coco_dir / "annotations" / "instances_val2017.json"
    if not train_json.exists() or not val_json.exists():
        raise SystemExit(
            f"Expected MOPAD COCO files at {train_json} and {val_json}. "
            "Download/extract the MOPAD dataset first."
        )
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    convert_coco_split(coco_dir, output_dir, "train", "train2017", train_json)
    convert_coco_split(coco_dir, output_dir, "valid", "val2017", val_json)
    data_yaml = output_dir / "palm_health_data.yaml"
    data_yaml.write_text(
        yaml.safe_dump(
            {
                "path": str(output_dir),
                "train": "train/images",
                "val": "valid/images",
                "nc": len(TARGET_NAMES),
                "names": TARGET_NAMES,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return data_yaml


def convert_coco_split(coco_dir: Path, output_dir: Path, split: str, image_folder: str, annotation_path: Path) -> None:
    payload = json.loads(annotation_path.read_text(encoding="utf-8"))
    categories = {category["id"]: normalize_class_name(category["name"]) for category in payload.get("categories", [])}
    images = {image["id"]: image for image in payload.get("images", [])}
    annotations_by_image: dict[int, list[dict]] = {}
    for annotation in payload.get("annotations", []):
        annotations_by_image.setdefault(annotation["image_id"], []).append(annotation)

    image_out = output_dir / split / "images"
    label_out = output_dir / split / "labels"
    image_out.mkdir(parents=True, exist_ok=True)
    label_out.mkdir(parents=True, exist_ok=True)

    kept_images = 0
    kept_boxes = 0
    for image_id, image in images.items():
        source_image = coco_dir / image_folder / image["file_name"]
        if not source_image.exists():
            continue
        label_lines = []
        width = float(image.get("width") or 0)
        height = float(image.get("height") or 0)
        if width <= 0 or height <= 0:
            continue
        for annotation in annotations_by_image.get(image_id, []):
            class_name = categories.get(annotation.get("category_id"))
            target_name = CLASS_MAP.get(class_name or "")
            if target_name is None:
                continue
            target_index = TARGET_NAMES.index(target_name)
            x, y, w, h = [float(value) for value in annotation.get("bbox", [0, 0, 0, 0])]
            if w <= 0 or h <= 0:
                continue
            x_center = (x + w / 2.0) / width
            y_center = (y + h / 2.0) / height
            label_lines.append(
                f"{target_index} {x_center:.8f} {y_center:.8f} {w / width:.8f} {h / height:.8f}"
            )
        if not label_lines:
            continue
        target_image = image_out / source_image.name
        link_or_copy(source_image, target_image)
        (label_out / f"{source_image.stem}.txt").write_text("\n".join(label_lines) + "\n", encoding="utf-8")
        kept_images += 1
        kept_boxes += len(label_lines)
    if kept_images == 0:
        raise SystemExit(f"No usable labeled images were converted for split {split}. Check category names and paths.")
    print(f"Converted {split}: {kept_images} images, {kept_boxes} boxes")


def normalize_class_name(name: object) -> str:
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")


def parse_batch(value: str) -> int | float:
    normalized = str(value).strip().lower()
    if normalized == "auto":
        return -1
    if "." in normalized:
        return float(normalized)
    return int(normalized)


def link_or_copy(source: Path, target: Path) -> None:
    if target.exists():
        return
    try:
        target.symlink_to(source)
    except OSError:
        shutil.copy2(source, target)


def train_yolo(args: argparse.Namespace, data_yaml: Path) -> Path:
    from ultralytics import YOLO

    model = YOLO(args.base_model)
    train_kwargs = {
        "data": str(data_yaml),
        "epochs": args.epochs,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "project": args.train_project,
        "name": args.train_name,
        "exist_ok": True,
        "fraction": args.fraction,
        "workers": args.workers,
    }
    if args.device:
        train_kwargs["device"] = args.device
    results = model.train(**train_kwargs)
    save_dir = Path(getattr(results, "save_dir", Path(args.train_project) / args.train_name))
    best_weights = save_dir / "weights" / "best.pt"
    if not best_weights.exists():
        raise SystemExit(f"Training finished but best weights were not found at {best_weights}")
    return best_weights


def validate_weights(path: Path) -> None:
    from ultralytics import YOLO

    model = YOLO(str(path))
    names = model.names.values() if isinstance(model.names, dict) else model.names
    normalized = {str(name).strip() for name in names}
    missing = set(TARGET_NAMES) - normalized
    if missing:
        raise SystemExit(f"Trained model is missing classes: {', '.join(sorted(missing))}")


if __name__ == "__main__":
    main()
