# Troubleshooting

## Frontend Shows Old UI

Hard refresh the browser. If needed:

```powershell
docker compose restart frontend
```

## Upload Fails

Check API logs:

```powershell
docker compose logs --tail=120 api
```

Common causes:

- Browser CORS from wrong URL
- File too large
- API container not running
- Missing block selection

## Stitching Fails

Check worker and NodeODM logs:

```powershell
docker compose logs --tail=160 worker
docker compose logs --tail=160 nodeodm
```

Common causes:

- Too few images
- Low overlap
- WhatsApp/compressed images
- Missing GPS
- Insufficient Docker memory
- Images from multiple unrelated areas in one job

Fixes:

- Use original SD-card photos.
- Fly 80% front overlap and 70% side overlap.
- Split large plantations into blocks.
- Use batch/low-memory mode.
- Increase Docker memory.

## Map Does Not Show Overlay

Check:

- Stitch job completed.
- COG asset exists.
- TiTiler is running.
- Selected block matches the map asset.
- Click **Zoom To Selected Area**.

## Inference Returns Zero Palms

Possible causes:

- Model confidence is too high for the current model.
- The model is not trained on your plantation imagery.
- Orthomosaic is too downsampled.
- Selected overlays have no matching detections.

Check the job summary in the UI or database. The starter model may need low confidence and human review.

## Model Missing

If inference fails with `model_not_configured`, add:

```text
models/palm_health.pt
```

or configure Roboflow fallback in `.env`.

## Docker Memory Is Too High

Stop active stitching jobs, then:

```powershell
docker compose restart nodeodm worker
```

For a full reset:

```powershell
docker compose down
docker compose up
```
