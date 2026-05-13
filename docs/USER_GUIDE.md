# User Guide

## Home

The Home page gives the working order for the app:

1. Plan a mission.
2. Upload imagery.
3. Stitch images.
4. Review map overlays.
5. Run inference.
6. Export reports and prescription bundles.

## Missions

Create estates and blocks before uploading imagery. A block should represent one operational plantation area.

Recommended block metadata:

- Estate name
- Block name
- Planting year
- Palm spacing in metres
- Target palms per hectare

## Upload Imagery

Upload original DJI photos from SD card or device export. Avoid WhatsApp/compressed images because they often remove GPS metadata.

Optional fields:

- Sensor width
- Focal length

The app can read many values from EXIF, but optional inputs help GSD and approximate size calculations when EXIF is incomplete.

## Stitching

Use Stitching to create orthomosaic map layers from uploaded photos.

Recommended workflow:

1. Review metadata readiness.
2. Use **Downsize + batch** for normal laptop memory.
3. Create stitch job.
4. Wait for progress.
5. Preview the result.
6. Open completed map on Map page.

If a stitch is distorted, use more overlap, original images, consistent altitude, and smaller blocks.

## Map Review

The Map sidebar starts collapsed so the map stays visible.

Sections:

- **Map overlays**: choose stitched COG layers.
- **Detection boxes**: show/hide bounding boxes and class filters.
- **Map actions**: zoom, locate, refresh.
- **AI Inference**: run or monitor queued inference.
- **Analytics**: block summary statistics.

Detection boxes cascade from selected overlays. If an overlay is unchecked, detections from that overlay are hidden and class totals update.

Bounding-box colors:

- Green: healthy
- Yellow: small young
- Orange: yellow stressed
- Red: dead

Hover a box to see:

- Class label
- Size
- Confidence

## Exports

Prescriptions export spot-treatment points as a bundle for downstream GIS/agricultural workflows. Treat v1 prescription maps as attention zones unless rates are configured and validated by agronomy staff.
