import os, time, json, argparse, requests, yaml, pathlib

TIMEOUT = float(os.getenv("TIMEOUT_SEC", "2"))
STATE_FILE = os.getenv("STATE_FILE", "/tmp/monitor_state.json")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
NOTIFICATION_SERVICE_URL = os.getenv("NOTIFICATION_SERVICE_URL", "http://10.0.3.199:8082")
TARGETS_FILE = os.getenv("TARGETS_FILE", "targets.yaml")

def load_targets():
    with open(TARGETS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f).get("targets", [])

def load_state():
    p = pathlib.Path(STATE_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_state(state):
    p = pathlib.Path(STATE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def notify(level, payload):
    """Send notifications via notification service and/or direct Slack"""
    notification_sent = False
    
    if NOTIFICATION_SERVICE_URL:
        try:
            print(f"🔔 Intentando enviar notificación a: {NOTIFICATION_SERVICE_URL}/notify")
            response = requests.post(
                f"{NOTIFICATION_SERVICE_URL}/notify", 
                json=payload, 
                timeout=10
            )
            print(f"✅ Notificación enviada exitosamente - Status: {response.status_code}")
            notification_sent = True
            return
        except Exception as e:
            print(f"❌ Error enviando notificación al service: {str(e)}")

     
    if SLACK_WEBHOOK_URL:
        try:
            print(f"🔔 Enviando fallback a Slack webhook")
            requests.post(SLACK_WEBHOOK_URL, json={
                "text": f"*[{level.upper()}]* {payload['service']} ({payload['status']})\n```{json.dumps(payload, ensure_ascii=False, indent=2)}```"
            }, timeout=3)
            print(f"✅ Notificación Slack enviada")
            notification_sent = True
        except Exception as e:
            print(f"❌ Error enviando notificación a Slack: {str(e)}")
    
    if not notification_sent:
        print(f"⚠️ No se pudo enviar notificación para {payload['service']} status {payload['status']}")

def do_get(url, headers):
    start = time.perf_counter()
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    latency = int((time.perf_counter() - start) * 1000)
    body = {}
    try:
        body = resp.json()
    except Exception:
        pass
    ok = 200 <= resp.status_code < 300
    logical_ok = ok and (str(body.get("status", "up")).lower() in ("up","ok","healthy") or body.get("ok", True))
    return logical_ok, latency, resp.status_code, body

def check_target(t):
    name = t["name"]
    headers = t.get("headers", {})
    threshold_ms = int(t.get("threshold_ms", 500))

    shallow_ok=deep_ok=False
    shallow_lat=deep_lat=0
    shallow_code=deep_code=0
    shallow_body=deep_body={}

    status_txt = "unknown"
    try:
        shallow_ok, shallow_lat, shallow_code, shallow_body = do_get(t["url"], headers)
        if "deep_url" in t:
            deep_ok, deep_lat, deep_code, deep_body = do_get(t["deep_url"], headers)
    except requests.exceptions.RequestException:
        status_txt = "failure"

    latency_ms = max(shallow_lat, deep_lat) if deep_lat else shallow_lat
    degraded = latency_ms > threshold_ms
    success = shallow_ok and (deep_ok if "deep_url" in t else True)

    if not success:
        status_txt = "failure"
    elif degraded:
        status_txt = "degradation"
    else:
        status_txt = "ok"

    payload = {
        "service": name,
        "status": status_txt,
        "latency_ms": latency_ms,
        "threshold_ms": threshold_ms,
        "http": {"shallow": shallow_code, "deep": deep_code},
        "bodies": {"shallow": shallow_body, "deep": deep_body},
        "ts": int(time.time()),
    }
    print(json.dumps({"level": status_txt, **payload}, ensure_ascii=False))
    return status_txt, payload

def run_once():
    targets = load_targets()
    state = load_state()
    changed = False
    for t in targets:
        name = t["name"]
        status_txt, payload = check_target(t)
        last = state.get(name, "unknown")
        # Notificar sólo cambios de estado para evitar ruido
        if last != status_txt:
            level = "warning" if status_txt == "degradation" else ("critical" if status_txt == "failure" else "info")
            notify(level, payload)
            state[name] = status_txt
            changed = True
    if changed:
        save_state(state)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Ejecuta en bucle")
    parser.add_argument("--interval", type=int, default=30, help="Intervalo en segundos")
    args = parser.parse_args()

    if args.loop:
        while True:
            run_once()
            time.sleep(args.interval)
    else:
        run_once()

if __name__ == "__main__":
    main()
