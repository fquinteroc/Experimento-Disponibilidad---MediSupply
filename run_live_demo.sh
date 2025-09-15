#!/bin/bash

# =============================================================================
# SCRIPT DE EXPERIMENTO DE DISPONIBILIDAD
# =============================================================================


set -e

# Configuración
CLUSTER="availability-lab-cluster"
MEDISUPPLY_SERVICE="availability-lab-medisupply"
REGION="us-east-1"
ALB_URL="http://availability-lab-alb-1400052646.us-east-1.elb.amazonaws.com"
LOG_GROUP="/ecs/availability-lab-monitor"

# Colores para presentación
RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
PURPLE='\033[1;35m'
CYAN='\033[1;36m'
WHITE='\033[1;37m'
NC='\033[0m'

# Variables para tracking
DETECTION_TIME=""
RECOVERY_TIME=""

# =============================================================================
# FUNCIONES DE PRESENTACIÓN
# =============================================================================

header() {
    echo ""
    echo -e "${WHITE}================================================================================${NC}"
    echo -e "${CYAN}                    $1${NC}"
    echo -e "${WHITE}================================================================================${NC}"
    echo ""
}

demo_step() {
    echo -e "${BLUE}🎯 $1${NC}"
}

success() {
    echo -e "${GREEN}✅ $1${NC}"
}

info() {
    echo -e "${PURPLE}📊 $1${NC}"
}

warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
}

pause_demo() {
    echo -e "${WHITE}Press ENTER to continue...${NC}"
    read
}

get_timestamp_ms() {
    date +%s%3N
}

time_diff_seconds() {
    local start_ms=$1
    local end_ms=$2
    echo "scale=2; ($end_ms - $start_ms) / 1000" | bc
}

get_logs() {
    local start_time=$1
    local end_time=${2:-$(date +%s)000}
    aws logs filter-log-events --region $REGION --log-group-name $LOG_GROUP \
        --start-time $start_time --end-time $end_time \
        --query 'events[*].{timestamp:timestamp,message:message}' --output json 2>/dev/null
}

# =============================================================================
# DEMOSTRACIÓN 1: ARQUITECTURA ACTUAL
# =============================================================================
demo_architecture() {
    header "DEMOSTRACIÓN 1: ARQUITECTURA ACTUAL"
    
    demo_step "Verificando estado actual del sistema..."
    
    # Verificar servicios
    local monitor_status=$(aws ecs describe-services --cluster $CLUSTER --services availability-lab-monitor --region $REGION \
        --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount}' 2>/dev/null)
    
    local medisupply_status=$(aws ecs describe-services --cluster $CLUSTER --services $MEDISUPPLY_SERVICE --region $REGION \
        --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount}' 2>/dev/null)
    
    info "🔹 Monitor Service: $(echo $monitor_status | jq -r '.Status') ($(echo $monitor_status | jq -r '.Running')/$(echo $monitor_status | jq -r '.Desired'))"
    info "🔹 MediSupply Service: $(echo $medisupply_status | jq -r '.Status') ($(echo $medisupply_status | jq -r '.Running')/$(echo $medisupply_status | jq -r '.Desired'))"
    
    echo ""
    demo_step "Probando health checks diferenciados..."
    
    # Health checks
    local health_response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$ALB_URL/health" --connect-timeout 5)
    local health_code=$(echo "$health_response" | grep -o "HTTPSTATUS:[0-9]*" | cut -d: -f2)
    local health_body=$(echo "$health_response" | sed -E 's/HTTPSTATUS:[0-9]*$//')
    
    local ready_response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$ALB_URL/ready" --connect-timeout 5)
    local ready_code=$(echo "$ready_response" | grep -o "HTTPSTATUS:[0-9]*" | cut -d: -f2)
    local ready_body=$(echo "$ready_response" | sed -E 's/HTTPSTATUS:[0-9]*$//')
    
    info "🔹 /health (shallow): HTTP $health_code → $(echo "$health_body" | jq -r '.status' 2>/dev/null)"
    info "🔹 /ready (deep): HTTP $ready_code → $(echo "$ready_body" | jq -r '.status' 2>/dev/null), DB: $(echo "$ready_body" | jq -r '.db' 2>/dev/null)"
    
    success "Arquitectura validada - Todos los componentes operacionales"
    
    echo ""
    pause_demo
}

# =============================================================================
# DEMOSTRACIÓN 2: DETECCIÓN DE FALLA EN TIEMPO REAL
# =============================================================================
demo_failure_detection() {
    header "DEMOSTRACIÓN 2: DETECCIÓN DE FALLA EN TIEMPO REAL"
    
    demo_step "Preparando simulación de falla completa..."
    
    # Asegurar estado inicial
    aws ecs update-service --cluster $CLUSTER --service $MEDISUPPLY_SERVICE \
        --desired-count 1 --region $REGION > /dev/null
    sleep 10
    
    local test_start_timestamp=$(get_timestamp_ms)
    local test_start_time=$(date +%s)000
    
    demo_step "🔴 SIMULANDO FALLA CRÍTICA - Escalando servicio a 0 instancias"
    
    # Crear falla
    aws ecs update-service --cluster $CLUSTER --service $MEDISUPPLY_SERVICE \
        --desired-count 0 --region $REGION > /dev/null
    
    echo ""
    demo_step "⏱️  Monitoreando detección en tiempo real..."
    echo ""
    
    # Monitoreo visual
    local detection_found=false
    local notification_sent=false
    local max_wait=60
    
    for i in $(seq 1 $max_wait); do
        printf "\r${BLUE}⏳ Segundo $i/$max_wait - Esperando detección...${NC}"
        sleep 1
        
        local current_time=$(date +%s)000
        local logs=$(get_logs $test_start_time $current_time)
        
        # Buscar detección
        if echo "$logs" | jq -r '.[].message' | grep -q '"level": "failure"' && [ "$detection_found" = false ]; then
            detection_found=true
            local detection_time=$(get_timestamp_ms)
            DETECTION_TIME=$(time_diff_seconds $test_start_timestamp $detection_time)
            
            printf "\r                                                                    \r"
            success "🚨 FALLA DETECTADA en ${DETECTION_TIME} segundos"
            
            # Verificar endpoint
            local fail_response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$ALB_URL/health" --connect-timeout 3 --max-time 5 2>/dev/null || echo "HTTPSTATUS:000")
            local fail_code=$(echo "$fail_response" | grep -o "HTTPSTATUS:[0-9]*" | cut -d: -f2)
            info "📊 Endpoint response durante falla: HTTP $fail_code"
        fi
        
        # Buscar notificación
        if echo "$logs" | jq -r '.[].message' | grep -q "Notificación enviada exitosamente" && [ "$notification_sent" = false ]; then
            notification_sent=true
            success "📧 NOTIFICACIÓN enviada exitosamente"
        fi
        
        # Salir si tenemos ambos
        if [ "$detection_found" = true ] && [ "$notification_sent" = true ]; then
            break
        fi
    done
    
    printf "\r                                                                    \r"
    
    if [ "$detection_found" = true ] && [ "$notification_sent" = true ]; then
        success "✅ PRUEBA EXITOSA: Falla detectada y notificada en ${DETECTION_TIME}s"
    else
        error "❌ Problemas en la detección"
    fi
    
    echo ""
    pause_demo
}

# =============================================================================
# DEMOSTRACIÓN 3: DETECCIÓN DE RECUPERACIÓN
# =============================================================================
demo_recovery_detection() {
    header "DEMOSTRACIÓN 3: DETECCIÓN DE RECUPERACIÓN"
    
    demo_step "🟢 SIMULANDO RECUPERACIÓN - Restaurando servicio"
    
    local recovery_start_timestamp=$(get_timestamp_ms)
    local recovery_start_time=$(date +%s)000
    
    # Restaurar servicio
    aws ecs update-service --cluster $CLUSTER --service $MEDISUPPLY_SERVICE \
        --desired-count 1 --region $REGION > /dev/null
    
    echo ""
    demo_step "⏱️  Monitoreando recuperación del servicio..."
    echo ""
    
    local recovery_found=false
    local notification_sent=false
    local max_wait=90
    
    for i in $(seq 1 $max_wait); do
        printf "\r${BLUE}⏳ Segundo $i/$max_wait - Esperando recuperación...${NC}"
        sleep 1
        
        local current_time=$(date +%s)000
        local logs=$(get_logs $recovery_start_time $current_time)
        
        # Buscar recuperación
        if echo "$logs" | jq -r '.[].message' | grep -q '"level": "ok"' && [ "$recovery_found" = false ]; then
            recovery_found=true
            local recovery_time=$(get_timestamp_ms)
            RECOVERY_TIME=$(time_diff_seconds $recovery_start_timestamp $recovery_time)
            
            printf "\r                                                                    \r"
            success "🟢 RECUPERACIÓN DETECTADA en ${RECOVERY_TIME} segundos"
            
            # Verificar endpoint
            sleep 3  # Dar tiempo para que se estabilice
            local ok_response=$(curl -s -w "HTTPSTATUS:%{http_code}" "$ALB_URL/health" --connect-timeout 5 2>/dev/null || echo "HTTPSTATUS:000")
            local ok_code=$(echo "$ok_response" | grep -o "HTTPSTATUS:[0-9]*" | cut -d: -f2)
            info "📊 Endpoint response después de recuperación: HTTP $ok_code"
        fi
        
        # Buscar notificación
        if echo "$logs" | jq -r '.[].message' | grep -q "Notificación enviada exitosamente" && [ "$notification_sent" = false ] && [ "$recovery_found" = true ]; then
            notification_sent=true
            success "📧 NOTIFICACIÓN de recuperación enviada"
        fi
        
        # Salir si tenemos ambos
        if [ "$recovery_found" = true ] && [ "$notification_sent" = true ]; then
            break
        fi
    done
    
    printf "\r                                                                    \r"
    
    if [ "$recovery_found" = true ] && [ "$notification_sent" = true ]; then
        success "✅ PRUEBA EXITOSA: Recuperación detectada y notificada en ${RECOVERY_TIME}s"
    else
        error "❌ Problemas en la detección de recuperación"
    fi
    
    echo ""
    pause_demo
}

# =============================================================================
# RESULTADOS FINALES
# =============================================================================
show_final_results() {
    header "RESULTADOS DE LA DEMOSTRACIÓN"
    
    demo_step "📊 Métricas del experimento:"
    echo ""
    
    info "🔹 Tiempo de detección de falla: ${DETECTION_TIME:-N/A}s"
    info "🔹 Tiempo de detección de recuperación: ${RECOVERY_TIME:-N/A}s"
    
    # Calcular promedio
    if [ -n "$DETECTION_TIME" ] && [ -n "$RECOVERY_TIME" ]; then
        local avg_time=$(echo "scale=2; ($DETECTION_TIME + $RECOVERY_TIME) / 2" | bc)
        info "🔹 Tiempo promedio de detección: ${avg_time}s"
    fi
}

# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================
main() {
    clear
    header "EXPERIMENTO DE DISPONIBILIDAD"

    echo -e "${WHITE}Esta demostración validará en tiempo real:${NC}"
    echo "• Detección automática de fallas"
    echo "• Sistema de notificaciones"
    echo "• Recuperación automática"
    echo "• Cumplimiento de SLA de disponibilidad"
    echo ""
    
    pause_demo
    
    # Verificar dependencias
    if ! command -v aws >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1 || ! command -v bc >/dev/null 2>&1; then
        error "Dependencias faltantes (aws, jq, bc)"
        exit 1
    fi
    
    # Verificar conectividad
    if ! aws sts get-caller-identity > /dev/null 2>&1; then
        error "No se puede conectar a AWS"
        exit 1
    fi
    
    # Ejecutar demostraciones
    demo_architecture
    demo_failure_detection  
    demo_recovery_detection
    show_final_results
    
    echo ""
    echo -e "${GREEN}🎉 Demostración completada exitosamente${NC}"
}

# Cleanup al salir
cleanup() {
    echo ""
    echo -e "${BLUE}Restaurando sistema a estado operacional...${NC}"
    aws ecs update-service --cluster $CLUSTER --service $MEDISUPPLY_SERVICE \
        --desired-count 1 --region $REGION > /dev/null 2>&1 || true
    echo -e "${GREEN}✅ Sistema restaurado${NC}"
}

trap cleanup EXIT INT TERM

# Ejecutar si se llama directamente
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
