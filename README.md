# local-availability-lab

Laboratorio local para validar disponibilidad con un **monitor ping/echo** que ejecuta health checks (shallow & deep) sobre un microservicio FastAPI y notifica cambios de estado (consola y opcional Slack). Incluye Postgres para probar fallas reales de dependencia.

## Requisitos
- Docker Desktop / Docker Engine + Docker Compose
- (Opcional) Slack Incoming Webhook

## Uso rápido

```bash
# 1) (Opcional) configurar Slack webhook
cp .env.example .env
# edita SLACK_WEBHOOK_URL si deseas notificaciones

# 2) Construir e iniciar
docker compose up -d --build

# 3) Verificar servicio
curl -s http://localhost:8080/health
curl -s http://localhost:8080/ready

# 4) Ver logs del monitor (detección y cambios de estado)
docker logs -f lab_monitor
```

## Simular fallas

- **DB caída**:
  ```bash
  docker stop lab_db
  docker start lab_db
  ```

- **Degradación por latencia**: edita `docker-compose.yml` en `svc` y pon `EXTRA_LATENCY_MS: "600"`, luego:
  ```bash
  docker compose up -d
  ```

- **Errores 5xx intermitentes**: establece `ERROR_RATE` a `0.2` (20%) y `up -d` de nuevo.

El monitor solo notifica **cambios** (`ok → degradation → failure` y viceversa) para evitar ruido.

## Estructura
```
local-availability-lab/
├─ docker-compose.yml
├─ .env.example
├─ db/init/01_init.sql
├─ service/{Dockerfile,requirements.txt,app.py}
└─ monitor/{Dockerfile,requirements.txt,monitor_local.py,targets.yaml}
```

## Endpoints
- `GET /health` — **shallow** health, no toca la BD.
- `GET /ready` — **deep** health, ejecuta `SELECT 1` contra Postgres.

## Notas
- El healthcheck del contenedor `db` espera a que exista la BD `app` para que `svc` arranque de forma confiable.
- Puedes ajustar el intervalo del monitor con `--interval` (por defecto 5s en `docker-compose.yml`).

¡Feliz hacking! 🛠️
