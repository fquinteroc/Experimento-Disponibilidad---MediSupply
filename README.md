# Experimento Disponibilidad MediSupply


##  **Descripción del Proyecto**

Este proyecto implementa un **sistema de monitoreo** que va más allá de la detección binaria tradicional (funciona/no funciona), proporcionando **clasificación granular tripartita** de estados de microservicios con capacidades de alertas preventivas.

---

##  **Inicio Rápido**

### **Opción 1: Usar Sistema Desplegado en AWS (Recomendado)**

El sistema está completamente funcional en AWS. Solo necesitas ejecutar los scripts:

```bash
# Clona el repositorio
git clone <tu-repositorio>
cd availability-lab

# Ejecuta demostración interactiva
./run_live_demo.sh
```

### **Opción 2: Desarrollo Local**

```bash
# Instalar dependencias
pip install -r service/requirements.txt
pip install -r monitor/requirements.txt

# Levantar servicios localmente
docker-compose up -d

# Verificar que funciona
curl http://localhost:8080/health
```

---

## 📡 **API Endpoints**

### **Health Check Endpoints**

#### **GET `/health` - Shallow Health Check**
```bash
curl -s "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/health" | jq
```

**Respuesta:**
```json
{
  "status": "up",
  "timestamp": "2024-09-14T21:30:45.123Z",
  "service": "medisupply"
}
```

#### **GET `/ready` - Deep Health Check**
```bash
curl -s "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/ready" | jq
```

**Respuesta:**
```json
{
  "status": "up",
  "db": null,
  "latency_ms": 12.45,
  "timestamp": "2024-09-14T21:30:45.123Z"
}
```

### ** Admin Endpoints (Control Dinámico)**

#### **GET `/admin/get-latency` - Consultar Latencia Actual**
```bash
curl -s "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/admin/get-latency" | jq
```

**Respuesta:**
```json
{
  "latency_ms": 0.0,
  "status": "normal"
}
```

#### **POST `/admin/set-latency` - Configurar Latencia Artificial**
```bash
curl -s -X POST "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/admin/set-latency" \
  -H "Content-Type: application/json" \
  -d '{"latency_ms": 800}' | jq
```

**Respuesta:**
```json
{
  "message": "Latencia establecida a 800ms",
  "status": "degraded",
  "previous_latency_ms": 0.0,
  "new_latency_ms": 800
}
```

#### **POST `/admin/reset-latency` - Resetear Latencia**
```bash
curl -s -X POST "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/admin/reset-latency" | jq
```

**Respuesta:**
```json
{
  "message": "Latencia reseteada",
  "status": "normal",
  "latency_ms": 0.0
}
```


---

## 🎯 **Demostración Manual de Estado DEGRADED**

### **1. Verificar Estado Inicial**
```bash
# Estado actual
curl -s "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/admin/get-latency" | jq

# Latencia normal del health check
time curl -s "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/ready" | jq '.latency_ms'
```

### **2. ⚠️ Simular Degradación**
```bash
# Configurar latencia alta (> 500ms threshold)
curl -s -X POST "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/admin/set-latency" \
  -H "Content-Type: application/json" \
  -d '{"latency_ms": 800}' | jq

# Verificar que se aplicó
time curl -s "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/ready" | jq
```

### **3. 🔄 Restaurar Normal**
```bash
# Resetear latencia
curl -s -X POST "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/admin/reset-latency" | jq

# Confirmar reset
curl -s "http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com/admin/get-latency" | jq
```

---

### **🔧 Servicios Desplegados**

| Servicio | Cluster | Task Definition | Puerto |
|----------|---------|----------------|--------|
| `availability-lab-medisupply` | availability-lab-cluster | :20 (admin-v1) | 8080 |
| `availability-lab-monitor` | availability-lab-cluster | :latest | 8081 |
| `availability-lab-notification` | availability-lab-cluster | :latest | 8082 |

### **📊 Logs en CloudWatch**

```bash
# Ver logs del monitor
aws logs filter-log-events \
  --region us-east-1 \
  --log-group-name "/ecs/availability-lab-monitor" \
  --start-time $(date -d '10 minutes ago' +%s)000

# Buscar detecciones de degradación
aws logs filter-log-events \
  --region us-east-1 \
  --log-group-name "/ecs/availability-lab-monitor" \
  --filter-pattern "degradation" \
  --start-time $(date -d '1 hour ago' +%s)000
```

---

## 🔍 **Sistema de Clasificación de Estados**

### **🟢 Estado OK**
- **Condición**: Latencia ≤ 500ms
- **Significado**: Servicio completamente operacional
- **Acción**: Ninguna (estado normal)

### **🟡 Estado DEGRADED**
- **Condición**: Latencia > 500ms pero servicio responde
- **Significado**: Servicio funcional pero con performance reducida
- **Acción**: ⚠️ **Alerta preventiva** - Intervención proactiva recomendada

### **🔴 Estado FAILURE**
- **Condición**: Servicio no responde o HTTP 5xx
- **Significado**: Servicio completamente inoperativo
- **Acción**: 🚨 **Alerta crítica** - Intervención inmediata requerida

---

## 🛠️ **Configuración**

### **Variables de Entorno**

```bash
# Configuración del Monitor
MONITOR_INTERVAL=60          # Polling cada 60 segundos
LATENCY_THRESHOLD=500        # Threshold para DEGRADED (ms)
FAILURE_THRESHOLD=1000       # Threshold para FAILURE (ms)

# Configuración de Notificaciones  
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_FROM=availability-lab@example.com
EMAIL_TO=admin@example.com

# AWS
AWS_REGION=us-east-1
CLOUDWATCH_LOG_GROUP=/ecs/availability-lab-monitor
```

### **Thresholds Configurables**

```yaml
# targets.yaml
services:
  - name: "medisupply"
    health_endpoint: "/health"
    ready_endpoint: "/ready"
    thresholds:
      degraded_ms: 500      # Latencia para considerar DEGRADED
      failure_ms: 1000      # Timeout para considerar FAILURE
```
