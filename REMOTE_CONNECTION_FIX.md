# Remote dashboard deployment

The running container uses the older Compose project and an empty configuration mount. The deployment override reconnects the existing configured workspace, enables explicit LAN binding, and advertises the host Wi-Fi address. Pairing authentication is unchanged. HTTPS is enabled in the mounted configuration.

## Apply after the Docker stop-permission failure is resolved

```sh
docker compose -p mark-lvi-main \
  -f '/home/hermes/.cline/worktrees/2adae/Mark-LVI-main/docker-compose.yml' \
  -f '/home/hermes/.cline/worktrees/ec023/jarvis personnel assistant/docker-compose.remote.yml' \
  up -d --no-deps --no-build jarvis
```

The attempted deployment failed with `cannot stop container: permission denied`. The old unhealthy container remains running; Compose also left a replacement container in Created state. No public router forwarding or host firewall changes were made by this repair.

## Verification after deployment

- HTTP on port 8000 should redirect to HTTPS on port 8001.
- Open `https://10.0.0.10:8001` from the same trusted Wi-Fi network.
- Confirm the certificate belongs to this dashboard before trusting its locally generated certificate.
- Pair using the application's Remote Control pairing flow. No authentication bypass was added.
- Confirm unauthenticated `/api/telemetry` returns HTTP 401.
- Confirm container health becomes healthy and test a command from the paired phone.

The current deployment uses an offscreen Qt interface. Access to its pairing UI may require a separate supported desktop/viewer workflow; successful phone pairing has not been verified.

The address is specific to this machine. Update both port bindings and KD_ADVERTISE_HOST if its Wi-Fi address changes. This override mounts the dashboard server file only; it does not deploy unrelated workspace changes into the older image.

A private configuration backup is stored at `/home/hermes/.cline/worktrees/ec023/jarvis personnel assistant/config/api_keys.before-remote-fix.json` with mode 0600. It contains credentials and must not be committed or shared.

## Recovery completed

After the user stopped the system Docker services and restarted Docker Snap, the previously running Patana services and Kronos were restarted successfully and reported healthy. Compose removed the stopped old Jarvis container, started the prepared replacement, and its temporary name was normalized to `mark-lvi-jarvis`.

Live verification from the host succeeded: HTTPS on `https://10.0.0.10:8001/` returned 200 using the generated certificate as the trusted CA (verification enabled); HTTP port 8000 redirected to HTTPS; unauthenticated `/api/telemetry` returned 401. Actual phone pairing and command execution remain untested.
