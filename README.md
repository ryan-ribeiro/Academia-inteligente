# Academia Inteligente

The current local slice includes OIDC authentication, administrator-only client
registration/search, and Keycloak-provisioned client first access.

## Local runtime

1. Copy `.env.example` to `.env` and replace the local placeholder passwords.
   Set a distinct `KEYCLOAK_PROVISIONING_CLIENT_SECRET`; it belongs only to the
   backend-to-Keycloak service account.
2. Run `docker-compose up --build`.
3. Apply the application schema:

   ```bash
   docker-compose run --rm backend alembic upgrade head
   ```

4. Open the frontend at `http://localhost:5173`, API health at
   `http://localhost:8000/health`, API OpenAPI at `http://localhost:8000/docs`,
   Keycloak at `http://localhost:8080`, and Mailpit at `http://localhost:8025`.

The Keycloak login and first-access screens use the repository-managed
`academia` theme from `keycloak/themes/academia`. Docker Compose mounts it into
the Keycloak container and the managed realm selects it. Its `/opt/keycloak/data`
directory is backed by the `keycloak_data` Docker volume, preserving provisioned
identities and realm state across normal container recreation. After changing theme
resources, recreate Keycloak with
`docker compose up -d --force-recreate keycloak`; a pre-existing realm is not
overwritten by `--import-realm`, so set the realm's Login theme to `academia`
once in the local admin console or recreate the local Keycloak realm/volume if
you need its imported settings reapplied.

Use the `APP_ADMIN_USERNAME` and `APP_ADMIN_PASSWORD` values from `.env` to
sign in to the application. The bootstrap application administrator needs only
those credentials: Keycloak does not require an e-mail address, first name, or
last name for it. `KEYCLOAK_ADMIN` credentials are only for the Keycloak
administration console. The frontend origin must be listed in
`CORS_ALLOWED_ORIGINS` (the local default is `http://localhost:5173`).

Local Docker Compose startup also creates these demo accounts automatically:

| Profile | Email | Initial password |
| --- | --- | --- |
| Administrator | `admin@academia.test` | `123` |
| Client | `cliente@academia.test` | `123` |
| Employee | `funcionario@academia.test` | `123` |
| Attendant | `atendente@academia.test` | `123` |
| Instructor | `instrutor@academia.test` | `123` |

Initialization runs after migrations and waits for Keycloak. Existing completed
demo accounts retain their passwords, data, and activation on subsequent starts.
An interrupted seed resumes using its persisted ownership marker; unrelated
accounts with the same email are rejected. Client and instructor records include
synthetic personal data; onboarding and biometric enrollment remain pending.
Employee and attendant accounts have only the capabilities already defined for
their roles. Set `SEED_DEMO_ACCOUNTS=false` to disable creation, or configure
`DEMO_ACCOUNT_PASSWORD` to change the initial password for newly created demo
users. The standalone production stack does not enable demo initialization.

When an administrator creates a client, the backend creates a Keycloak user
with only the `client` role and sends a Mailpit first-access message. Open the
message at `http://localhost:8025`, follow its Keycloak link, define the
client's password, and then sign in as that client. The password and action
token never enter PostgreSQL. A local client created before provisioning can be
selected under **Clientes** and retried with **Provisionar acesso**.

Clients reach pending onboarding after signing in; the admin panel no longer
requires an onboarding invitation. Existing secure invitation links remain valid
under their separate 24-hour policy.

For password recovery, open **Clientes → client details → Redefinir senha** as
an administrator, or **Meu perfil → settings cog → Redefinir senha** as the
client. On the login screen, use **Esqueceu sua senha?** and enter the registered
email. These flows send a Keycloak password-setup link valid for **15 minutes** to
the registered email. In local Docker, retrieve that email in Mailpit at
`http://localhost:8025`; it is not delivered to an external inbox. The password
changes only when the user completes Keycloak's form. Admin/profile requests
share a one-minute cooldown. Inactive/unlinked accounts or pending identity updates
must be resolved before sending from admin/profile actions. The Keycloak version
is unchanged. Existing installations need `alembic upgrade head` (migration
`20260927_31`) before restarting the backend.

Fresh realms include login recovery automatically. Existing local realms need
the targeted update below; it preserves users and other realm settings and uses
the running container's configured bootstrap administrator credentials:

```bash
docker compose exec -T keycloak bash -s < keycloak/enable-password-recovery.sh
```

For an existing production deployment, execute the same script in that
deployment's Keycloak container with its configured realm-administrator
credentials. It also supports the deployment's mounted administrator-password
secret. The script removes its temporary administrator session file on exit.

### Local facial-access pilot

The owner-only facial-access pilot runs through the local Docker `biometrics`
profile. New client/staff registrations now require successful webcam enrollment
or verified reuse of the same person's face. Administrators operate
`/admin/acesso-facial`; release is simulated and occupancy changes only after
explicit passage confirmation or a reasoned correction. See the
[pilot startup, recovery and owner checklist](docs/tasks/44-facial-pilot-verification.md).
Real webcam verification is still pending; no liveness or hardware readiness is claimed.

### Local conversational AI with Ollama

OpenAI remains the initial configured provider. For local development without
an API cost, use the optional internal Ollama Compose profile. Set the following
values in `.env` (a smaller compatible model such as `qwen3:4b` can be used
instead):

```bash
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=qwen3:8b
OLLAMA_TIMEOUT_SECONDS=120
```

Start it when needed:

```bash
docker compose --profile ollama up -d
```

The first execution downloads the configured model. It is then retained in the
`ollama_data` Docker volume. Recreate the backend with
`docker compose up --build -d backend`, then sign in as a client and test
`/onboarding/conversa`. To stop local inference without deleting the model,
run `docker compose --profile ollama stop ollama`; start it again with
`docker compose --profile ollama start ollama`.

The Ollama API is accessible only to Compose services; this project does not
publish port 11434. To use an Ollama process installed directly on the Linux
host instead, set `OLLAMA_BASE_URL=http://host.docker.internal:11434`; the
Compose backend includes the required Linux host-gateway mapping.

The optional Compose service is pinned to NVIDIA GPU `0` and its CUDA 12 runner;
it does not silently use a CPU runner. The host must have a compatible NVIDIA
driver and NVIDIA Container Toolkit configured for Docker; otherwise the Ollama
service cannot perform inference until GPU access is restored. This project does
not configure a host GPU driver or expose GPU services publicly.

For a fresh local realm, `docker-compose up --build` imports the provisioning
service account and Mailpit SMTP configuration. Existing Keycloak realms are
not overwritten by Keycloak import; configure the same `academia-provisioner`
service account and SMTP settings through the Keycloak admin console before
using this flow.

Only the UI, API, Keycloak, and Mailpit are bound to loopback addresses.
PostgreSQL is available exclusively on the internal Compose network. For Internet
deployment, use the separate [production deployment guide](docs/deployment/README.md)
and `docker-compose.production.yml`. Only its HTTPS/redirect gateway is public;
Docker forwarding requires firewall rules in addition to UFW. Do not expose the
development stack directly.

## Quality checks

Run these commands through the containers so they use the approved baseline:

```bash
docker-compose run --rm backend ruff check .
docker-compose run --rm backend ruff format --check .
docker-compose run --rm backend pytest
docker-compose run --rm frontend npm run lint
docker-compose run --rm frontend npm run build
docker-compose run --rm frontend npm test
```

`docker-compose up --build` runs service health checks. To inspect them, use
`docker-compose ps`.

The frontend lockfile must be generated with the approved Node image before a
release build is used: `docker-compose run --rm frontend npm install`. This
foundation environment could not generate it because Docker daemon access was
unavailable during setup.
