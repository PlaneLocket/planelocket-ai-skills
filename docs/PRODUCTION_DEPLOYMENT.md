# Production HTTPS deployment — Kvasir

**Status:** Operator reports deployment and validation phases A–G8 completed on 2026-10-28. This runbook records the target topology; the final live configuration and test output have not been independently captured into Git.

## Endpoint and authentication

- Base URL: `https://ai.planelocket.com` (UniFi internal DNS resolves to Heimdall `10.10.1.2`).
- `GET /health`: unauthenticated health endpoint.
- `GET /docs`: Swagger UI; use it for the current request schema.
- `POST /investigate`: bearer-token protected; obtain `PLANELOCKET_API_TOKEN` from private secret storage.
- Do not commit or paste the token or the application's `.env` into Git or tickets.

## Request path

```text
wired LAN 10.10.1.0/24 OR Mimir 10.10.90.145
    -> Heimdall 10.10.1.2:443 (nginx stream SNI/source-IP ACL)
    -> Heimdall 127.0.0.1:8453 (TLS termination)
    -> Kvasir 10.10.1.70:8000 (UFW: Heimdall only)
    -> FastAPI bearer authentication -> local agent/Ollama
```

The HTTP proxy does not see the original client IP because the stream router does not preserve it. **Client allowlisting belongs in the stream router**, not the FastAPI vhost. The hostname is not publicly advertised via A/AAAA records; this alone does not prevent public access. See the [infrastructure runbook](https://github.com/PlaneLocket/planelocket-infrastructure/blob/main/docs/planelocket-ai/DEPLOYMENT.md) (link resolves after that PR merges).

## Service operations (Kvasir)

Repository: `/home/looper/projects/planelocket-ai-skills`; Python venv: `.venv`; systemd unit: `/etc/systemd/system/planelocket-ai.service`; account: `looper`.

Expected Uvicorn command in `ExecStart`:

```ini
ExecStart=/home/looper/projects/planelocket-ai-skills/.venv/bin/python -m uvicorn planelocket_agent.api:app --host 10.10.1.70 --port 8000
```

Check without modifying:

```bash
sudo systemctl status planelocket-ai.service --no-pager
sudo systemctl cat planelocket-ai.service
sudo journalctl -u planelocket-ai.service -n 100 --no-pager
sudo ufw status verbose
sudo ss -ltnp | grep ':8000'
curl --fail --silent --show-error http://10.10.1.70:8000/health
```

After an approved unit change: `sudo systemd-analyze verify /etc/systemd/system/planelocket-ai.service`, `sudo systemctl daemon-reload`, `sudo systemctl restart planelocket-ai.service`. Verify health from Kvasir and Heimdall.

The UFW allow rule for TCP 8000 should permit **only** `10.10.1.2`; existing SSH and Ollama permissions are separate. Mimir should access the HTTPS gateway, **not** port 8000 directly. The old SSH tunnel targeting `127.0.0.1:8000` no longer targets the production listener.

## Validation

```bash
# Mimir, via the normal HTTPS ingress:
curl -i https://ai.planelocket.com/health

# Missing bearer token must be rejected:
curl -i -X POST https://ai.planelocket.com/investigate \
  -H 'Content-Type: application/json' -d '{}'
```

For an authorized investigation, use Swagger's current schema and bearer authorization; confirm a model-backed response and check service logs. Negative tests must show other Wi-Fi clients and internet clients denied at Heimdall, and direct Kvasir port 8000 denied except from Heimdall. Recheck existing HTTPS routes after nginx edits. Certbot DNS-01 renewal is managed on Heimdall, not Kvasir.

## Recovery / rollback

Recover the application source from this repository, restore its venv dependencies and private `.env`/bearer token, Ollama model and `planelocket-ai.service`; restore Kvasir's IP reservation and narrow UFW rule; confirm Heimdall-to-Kvasir `/health` before restoring the HTTPS route. Follow the [infrastructure deployment and recovery runbook](https://github.com/PlaneLocket/planelocket-infrastructure/blob/main/docs/planelocket-ai/DEPLOYMENT.md) for nginx, Cloudflare DNS-01 and UniFi DNS. Do not overwrite existing production nginx routes or reset UFW.

To revert to local-only API operation, restore the saved pre-HTTPS systemd unit with `--host 127.0.0.1`, reload systemd and restart, and remove **only** the AI port-8000 UFW rule after checking numbered rules. Revert Heimdall's AI route first to avoid a broken public-facing hostname. No full restore drill has been recorded.
