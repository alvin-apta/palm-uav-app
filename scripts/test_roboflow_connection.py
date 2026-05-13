from __future__ import annotations

import argparse
import json
import mimetypes
import os
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageOps


def main() -> int:
    parser = argparse.ArgumentParser(description="Test hosted Roboflow inference without printing the API key.")
    parser.add_argument("--image", required=True, help="Path to a local image inside the container.")
    parser.add_argument("--confidence", type=int, default=35)
    parser.add_argument("--overlap", type=int, default=30)
    parser.add_argument("--max-side", type=int, default=1600)
    args = parser.parse_args()

    key = os.getenv("ROBOFLOW_API_KEY", "").strip()
    model_id = os.getenv("ROBOFLOW_MODEL_ID", "").strip()
    if not key:
        print(json.dumps({"ok": False, "error": "ROBOFLOW_API_KEY is empty"}))
        return 2
    if not model_id:
        print(json.dumps({"ok": False, "error": "ROBOFLOW_MODEL_ID is empty"}))
        return 2

    image_path = Path(args.image)
    if not image_path.exists():
        print(json.dumps({"ok": False, "error": f"Image not found: {image_path}"}))
        return 2

    url = f"https://detect.roboflow.com/{model_id}"
    mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"

    image_file, upload_name, mime_type, resize_scale = prepare_upload(image_path, args.max_side)
    try:
        response = httpx.post(
            url,
            params={
                "api_key": key,
                "confidence": args.confidence,
                "overlap": args.overlap,
            },
            files={"file": (upload_name, image_file, mime_type)},
            timeout=90,
        )
    finally:
        image_file.close()

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}

    predictions = payload.get("predictions", []) if isinstance(payload, dict) else []
    classes = sorted({str(item.get("class")) for item in predictions if isinstance(item, dict) and item.get("class")})
    print(
        json.dumps(
            {
                "ok": response.is_success,
                "status_code": response.status_code,
                "model_id": model_id,
                "prediction_count": len(predictions),
                "classes_seen": classes,
                "resize_scale": resize_scale,
                "max_side": args.max_side,
                "error": payload.get("message") or payload.get("error") if isinstance(payload, dict) else None,
            },
            indent=2,
        )
    )
    return 0 if response.is_success else 1


def prepare_upload(image_path: Path, max_side: int):
    max_side = max(320, max_side)
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        largest_side = max(width, height)
        if largest_side <= max_side:
            return image_path.open("rb"), image_path.name, mimetypes.guess_type(image_path.name)[0] or "image/jpeg", 1.0

        resize_scale = max_side / largest_side
        resized_size = (max(1, round(width * resize_scale)), max(1, round(height * resize_scale)))
        resized = image.convert("RGB").resize(resized_size, Image.Resampling.LANCZOS)
        buffer = BytesIO()
        resized.save(buffer, format="JPEG", quality=85, optimize=True)
        buffer.seek(0)
        return buffer, f"{image_path.stem}_roboflow.jpg", "image/jpeg", resize_scale


if __name__ == "__main__":
    raise SystemExit(main())
