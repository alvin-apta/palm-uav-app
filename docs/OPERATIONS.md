# Operations

## Common Commands

```powershell
docker compose up --build
docker compose ps
docker compose logs --tail=120 api
docker compose logs --tail=120 worker
docker compose logs --tail=120 nodeodm
docker compose restart api worker frontend
docker compose down
```

## Runtime Data

Runtime files live under `data/`:

- Uploaded photos
- ODM projects
- COG outputs
- Exports
- Training runs

This folder is ignored by Git. Back it up separately if you need to keep analysis history.

## Database Backup

Create a backup:

```powershell
docker compose exec postgres pg_dump -U palmops palmops > palmops_backup.sql
```

Restore:

```powershell
Get-Content palmops_backup.sql | docker compose exec -T postgres psql -U palmops -d palmops
```

## Model Backup

The active model is:

```text
models/palm_health.pt
```

Keep production-trained models in external storage or Git LFS if they become large.

## Memory Management

Stitching can consume significant memory. Prefer:

- Smaller blocks
- Original photos with good overlap
- Low-memory mode
- Batch stitching
- One stitch job at a time

If Docker Desktop memory grows too high, stop old jobs and restart NodeODM:

```powershell
docker compose restart nodeodm worker
```

## Production Notes

Before real production use:

- Change `SECRET_KEY`.
- Change default owner password.
- Put the app behind HTTPS.
- Move PostgreSQL to managed storage or scheduled backups.
- Use stronger, field-validated YOLO weights.
- Store large imagery in object storage.
- Add user-specific block permissions.
