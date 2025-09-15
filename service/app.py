import os, time, random, asyncio
from fastapi import FastAPI, Response, status, Request
import asyncpg

app = FastAPI()
DB_DSN = os.getenv("DB_DSN", "postgresql://app:app@db:5432/app")
EXTRA_LATENCY_MS = float(os.getenv("EXTRA_LATENCY_MS", "0"))
ERROR_RATE = float(os.getenv("ERROR_RATE", "0.0"))

async def maybe_degrade():
    # Simula latencia adicional y errores controlados (para pruebas)
    if EXTRA_LATENCY_MS > 0:
        await asyncio.sleep(EXTRA_LATENCY_MS / 1000.0)
    if ERROR_RATE > 0 and random.random() < ERROR_RATE:
        raise RuntimeError("Error inyectado para pruebas")

@app.get("/health")
async def health():
    await maybe_degrade()
    return {"status": "up"}

@app.get("/ready")
async def ready(response: Response):
    start = time.perf_counter()
    try:
        await maybe_degrade()
        
        # Si no hay DB_DSN configurado, solo verificamos que el servicio esté up
        if not DB_DSN or DB_DSN.strip() == "":
            latency_ms = int((time.perf_counter() - start) * 1000)
            return {"status": "up", "db": None, "latency_ms": latency_ms}
        
        # Si hay DB_DSN, verificamos la conexión a la base de datos
        conn = await asyncpg.connect(dsn=DB_DSN, timeout=1.5)
        row = await conn.fetchval("SELECT 1;")
        await conn.close()
        latency_ms = int((time.perf_counter() - start) * 1000)
        ok = (row == 1)
        status_txt = "up" if ok else "down"
        if ok:
            return {"status": status_txt, "db": True, "latency_ms": latency_ms}
        else:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": status_txt, "db": False, "latency_ms": latency_ms}
    except Exception:
        latency_ms = int((time.perf_counter() - start) * 1000)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "down", "db": False, "latency_ms": latency_ms}

# Endpoints para control dinámico de latencia (para pruebas de DEGRADED)
@app.post("/admin/set-latency")
async def set_latency(request: Request):
    """Establece latencia artificial en milisegundos para pruebas de degradación"""
    global EXTRA_LATENCY_MS
    data = await request.json()
    latency_ms = int(data.get("latency_ms", 0))
    EXTRA_LATENCY_MS = float(latency_ms)
    return {
        "message": f"Latencia establecida a {latency_ms}ms",
        "latency_ms": EXTRA_LATENCY_MS,
        "status": "degraded" if latency_ms > 500 else "normal"
    }

@app.get("/admin/get-latency")
async def get_latency():
    """Obtiene la latencia artificial configurada"""
    return {
        "latency_ms": EXTRA_LATENCY_MS,
        "status": "degraded" if EXTRA_LATENCY_MS > 500 else "normal"
    }

@app.post("/admin/reset-latency")
async def reset_latency():
    """Resetea la latencia artificial a 0"""
    global EXTRA_LATENCY_MS
    EXTRA_LATENCY_MS = 0.0
    return {
        "message": "Latencia reseteada",
        "latency_ms": EXTRA_LATENCY_MS,
        "status": "normal"
    }
