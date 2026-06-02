# Cloudflare public access

The app is exposed through the `public-gateway` nginx service. It serves:

- `/` -> frontend
- `/api/` -> backend API
- `/titiler/` -> TiTiler raster tiles

## Hostname

Use this public hostname:

```text
apta.works
```

The backend CORS defaults also allow HTTPS subdomains such as:

```text
app.apta.works
palm.apta.works
```

## Cloudflare Tunnel

In Cloudflare Zero Trust, add a Public Hostname to the tunnel:

```text
Hostname: apta.works
Service:  http://public-gateway:80
```

If you prefer a subdomain, use the same service target:

```text
Hostname: app.apta.works
Service:  http://public-gateway:80
```

Put the tunnel token in `.env`:

```text
CLOUDFLARE_TUNNEL_TOKEN=...
```

Then start the tunnel container:

```bash
docker compose --profile cloudflare up -d cloudflared
```
