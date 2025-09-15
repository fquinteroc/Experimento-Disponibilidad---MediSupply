import os
import time
import json
import requests
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiosmtplib
from fastapi import FastAPI, HTTPException
import boto3
from botocore.exceptions import ClientError
import asyncpg
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Notification Service", description="Servicio de notificaciones para availability lab")

# Configuration
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DB_DSN = os.getenv("DB_DSN", "")
DB_ENABLED = os.getenv("DB_ENABLED", "false").lower() == "true"

# Email Configuration
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USERNAME)
EMAIL_TO = os.getenv("EMAIL_TO", "").split(",") if os.getenv("EMAIL_TO") else []

# Initialize AWS SNS client
sns_client = boto3.client('sns', region_name=AWS_REGION) if SNS_TOPIC_ARN else None

@app.get("/health")
async def health():
    return {"status": "up", "service": "notification"}

@app.get("/config")
async def config():
    """Return current notification configuration"""
    return {
        "slack_configured": bool(SLACK_WEBHOOK_URL),
        "sns_configured": bool(SNS_TOPIC_ARN and sns_client),
        "email_configured": bool(EMAIL_TO and SMTP_USERNAME and SMTP_PASSWORD),
        "database_configured": bool(DB_ENABLED and DB_DSN),
        "email_recipients": len(EMAIL_TO) if EMAIL_TO else 0,
        "smtp_host": SMTP_HOST if EMAIL_TO else None,
        "smtp_port": SMTP_PORT if EMAIL_TO else None
    }

@app.get("/notifications")
async def get_notifications(limit: int = 50):
    """Get recent notifications from database"""
    try:
        conn = await asyncpg.connect(dsn=DB_DSN, timeout=5)
        
        rows = await conn.fetch("""
            SELECT id, service_name, status, message, latency_ms, 
                   http_shallow_status, http_deep_status, 
                   timestamp_event, timestamp_notified
            FROM notifications 
            ORDER BY timestamp_notified DESC 
            LIMIT $1
        """, limit)
        
        await conn.close()
        
        notifications = []
        for row in rows:
            notifications.append({
                "id": row['id'],
                "service_name": row['service_name'],
                "status": row['status'],
                "message": row['message'],
                "latency_ms": row['latency_ms'],
                "http_shallow_status": row['http_shallow_status'],
                "http_deep_status": row['http_deep_status'],
                "timestamp_event": row['timestamp_event'].isoformat(),
                "timestamp_notified": row['timestamp_notified'].isoformat()
            })
        
        return {
            "notifications": notifications,
            "count": len(notifications)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/notifications/stats")
async def get_notification_stats():
    """Get notification statistics"""
    try:
        conn = await asyncpg.connect(dsn=DB_DSN, timeout=5)
        
        # Get counts by status
        status_counts = await conn.fetch("""
            SELECT status, COUNT(*) as count
            FROM notifications
            WHERE timestamp_notified >= NOW() - INTERVAL '24 hours'
            GROUP BY status
            ORDER BY count DESC
        """)
        
        # Get recent activity
        recent_count = await conn.fetchval("""
            SELECT COUNT(*)
            FROM notifications
            WHERE timestamp_notified >= NOW() - INTERVAL '1 hour'
        """)
        
        # Get total notifications
        total_count = await conn.fetchval("SELECT COUNT(*) FROM notifications")
        
        await conn.close()
        
        stats = {
            "total_notifications": total_count,
            "last_24h_by_status": {row['status']: row['count'] for row in status_counts},
            "last_hour_count": recent_count
        }
        
        return stats
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/notify")
async def notify(payload: dict):
    """
    Envía notificaciones via Slack, SNS y/o Email y guarda en base de datos
    """
    logger.info(f"🔔 Received notification request: {json.dumps(payload, indent=2)}")
    
    try:
        message = format_message(payload)
        results = {}
        logger.info(f"📝 Formatted message: {message}")
        
        # Save to database if enabled and configured
        if DB_ENABLED and DB_DSN:
            logger.info("💾 Database is enabled, saving notification...")
            db_result = await save_notification_to_db(payload)
            results["database"] = db_result
            logger.info(f"💾 Database result: {db_result}")
        else:
            logger.info("💾 Database is disabled")
        
        # Send to Slack if configured
        if SLACK_WEBHOOK_URL:
            logger.info("📱 Slack webhook configured, sending notification...")
            slack_result = await send_slack_notification(message, payload)
            results["slack"] = slack_result
            logger.info(f"📱 Slack result: {slack_result}")
        else:
            logger.info("📱 Slack webhook not configured")
        
        # Send to SNS if configured
        if sns_client and SNS_TOPIC_ARN:
            logger.info("📨 SNS configured, sending notification...")
            sns_result = await send_sns_notification(message, payload)
            results["sns"] = sns_result
            logger.info(f"📨 SNS result: {sns_result}")
        else:
            logger.info("📨 SNS not configured")
            
        # Send Email if configured
        logger.info(f"📧 Checking email configuration:")
        logger.info(f"📧 EMAIL_TO: {EMAIL_TO}")
        logger.info(f"📧 SMTP_USERNAME: {SMTP_USERNAME}")
        logger.info(f"📧 SMTP_PASSWORD: {'***' if SMTP_PASSWORD else 'NOT_SET'}")
        
        if EMAIL_TO and SMTP_USERNAME and SMTP_PASSWORD:
            logger.info("📧 Email is configured, sending notification...")
            email_result = await send_email_notification(message, payload)
            results["email"] = email_result
            logger.info(f"📧 Email result: {email_result}")
        else:
            logger.warning("📧 Email not properly configured!")
            logger.warning(f"📧 EMAIL_TO present: {bool(EMAIL_TO)}")
            logger.warning(f"📧 SMTP_USERNAME present: {bool(SMTP_USERNAME)}")
            logger.warning(f"📧 SMTP_PASSWORD present: {bool(SMTP_PASSWORD)}")
            results["email"] = {"success": False, "error": "Email not configured"}
            
        logger.info(f"✅ Notification processing completed. Results: {results}")
        
        return {
            "status": "sent",
            "timestamp": int(time.time()),
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Notification failed: {str(e)}")

def format_message(payload):
    """Format message for notifications"""
    service = payload.get('service', 'unknown')
    status = payload.get('status', 'unknown')
    latency_ms = payload.get('latency_ms', 0)
    
    emoji = {"ok": "✅", "degradation": "⚠️", "failure": "🚨"}.get(status, "❓")
    
    return f"{emoji} Service: {service} | Status: {status.upper()} | Latency: {latency_ms}ms"

async def save_notification_to_db(payload):
    """Save notification event to database"""
    try:
        conn = await asyncpg.connect(dsn=DB_DSN, timeout=5)
        
        # Create notifications table if it doesn't exist
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                service_name VARCHAR(255) NOT NULL,
                status VARCHAR(50) NOT NULL,
                message TEXT,
                latency_ms INTEGER,
                http_shallow_status INTEGER,
                http_deep_status INTEGER,
                timestamp_event TIMESTAMP WITH TIME ZONE,
                timestamp_notified TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                payload JSONB
            )
        """)
        
        # Extract data from payload
        service_name = payload.get('service', 'unknown')
        status = payload.get('status', 'unknown')
        message = payload.get('message', '')
        latency_ms = payload.get('latency_ms', 0)
        
        # Extract HTTP status codes
        http_info = payload.get('http', {})
        http_shallow = http_info.get('shallow') if http_info else None
        http_deep = http_info.get('deep') if http_info else None
        
        # Parse timestamp
        event_timestamp = payload.get('timestamp')
        if event_timestamp:
            # Convert from ISO string to timestamp
            import datetime
            if isinstance(event_timestamp, str):
                event_ts = datetime.datetime.fromisoformat(event_timestamp.replace('Z', '+00:00'))
            else:
                event_ts = datetime.datetime.fromtimestamp(event_timestamp, datetime.timezone.utc)
        else:
            event_ts = datetime.datetime.now(datetime.timezone.utc)
        
        # Insert notification
        await conn.execute("""
            INSERT INTO notifications 
            (service_name, status, message, latency_ms, http_shallow_status, http_deep_status, timestamp_event, payload)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, service_name, status, message, latency_ms, http_shallow, http_deep, event_ts, json.dumps(payload))
        
        await conn.close()
        
        return {"success": True, "message": "Saved to database"}
        
    except Exception as e:
        return {"success": False, "error": f"Database error: {str(e)}"}

async def send_slack_notification(message, payload):
    """Send notification to Slack"""
    try:
        slack_payload = {
            "text": message,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{message}*"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Service:* {payload.get('service')}"},
                        {"type": "mrkdwn", "text": f"*Status:* {payload.get('status')}"},
                        {"type": "mrkdwn", "text": f"*Latency:* {payload.get('latency_ms')}ms"},
                        {"type": "mrkdwn", "text": f"*Timestamp:* {payload.get('ts')}"}
                    ]
                }
            ]
        }
        
        response = requests.post(SLACK_WEBHOOK_URL, json=slack_payload, timeout=5)
        return {"success": response.status_code == 200, "status_code": response.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def send_sns_notification(message, payload):
    """Send notification via AWS SNS"""
    try:
        response = sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(payload, indent=2),
            Subject=message
        )
        return {"success": True, "message_id": response['MessageId']}
    except ClientError as e:
        return {"success": False, "error": str(e)}

async def send_email_notification(message, payload):
    """Send notification via Email"""
    logger.info("📧 Starting email notification process...")
    
    try:
        logger.info(f"📧 Creating email message for recipients: {EMAIL_TO}")
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"[MediSupply Alert] {payload.get('service', 'Unknown')} - {payload.get('status', 'Unknown').upper()}"
        msg['From'] = EMAIL_FROM
        msg['To'] = ", ".join(EMAIL_TO)
        
        logger.info(f"📧 Email subject: {msg['Subject']}")
        logger.info(f"📧 Email from: {msg['From']}")
        logger.info(f"📧 Email to: {msg['To']}")
        
        # Create HTML content
        html_content = create_email_html(payload, message)
        
        # Create text content
        text_content = create_email_text(payload, message)
        
        logger.info(f"📧 Email content created (HTML: {len(html_content)} chars, Text: {len(text_content)} chars)")
        
        # Attach parts
        part1 = MIMEText(text_content, 'plain')
        part2 = MIMEText(html_content, 'html')
        
        msg.attach(part1)
        msg.attach(part2)
        
        logger.info(f"📧 Connecting to SMTP server: {SMTP_HOST}:{SMTP_PORT}")
        
        # Send email
        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            start_tls=SMTP_USE_TLS,
            username=SMTP_USERNAME,
            password=SMTP_PASSWORD,
        )
        
        logger.info("📧 ✅ Email sent successfully!")
        
        return {"success": True, "recipients": len(EMAIL_TO)}
    except Exception as e:
        logger.error(f"📧 ❌ Email sending failed: {str(e)}")
        logger.error(f"📧 Exception type: {type(e).__name__}")
        return {"success": False, "error": str(e)}

def create_email_text(payload, message):
    """Create plain text email content"""
    service = payload.get('service', 'Unknown')
    status = payload.get('status', 'unknown')
    latency_ms = payload.get('latency_ms', 0)
    timestamp = payload.get('ts', int(time.time()))
    
    # Convert timestamp to readable format
    readable_time = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(timestamp))
    
    http_info = payload.get('http', {})
    shallow_status = http_info.get('shallow', 'N/A')
    deep_status = http_info.get('deep', 'N/A')
    
    text = f"""
MediSupply Availability Alert

Service: {service}
Status: {status.upper()}
Latency: {latency_ms}ms
Timestamp: {readable_time}

Health Check Details:
- Shallow Health: HTTP {shallow_status}
- Deep Health: HTTP {deep_status}

This is an automated alert from the MediSupply Availability Monitoring System.
"""
    return text.strip()

def create_email_html(payload, message):
    """Create HTML email content"""
    service = payload.get('service', 'Unknown')
    status = payload.get('status', 'unknown')
    latency_ms = payload.get('latency_ms', 0)
    timestamp = payload.get('ts', int(time.time()))
    
    # Convert timestamp to readable format
    readable_time = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(timestamp))
    
    # Status colors
    status_colors = {
        'ok': '#28a745',      # Green
        'degradation': '#ffc107',  # Yellow
        'failure': '#dc3545'   # Red
    }
    
    status_color = status_colors.get(status, '#6c757d')
    
    # Emojis
    status_emoji = {'ok': '✅', 'degradation': '⚠️', 'failure': '🚨'}.get(status, '❓')
    
    http_info = payload.get('http', {})
    shallow_status = http_info.get('shallow', 'N/A')
    deep_status = http_info.get('deep', 'N/A')
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>MediSupply Alert</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f8f9fa; }}
            .container {{ max-width: 600px; margin: 0 auto; background-color: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .header {{ background-color: {status_color}; color: white; padding: 20px; border-radius: 8px 8px 0 0; text-align: center; }}
            .content {{ padding: 20px; }}
            .status-badge {{ display: inline-block; padding: 5px 10px; border-radius: 4px; font-weight: bold; color: white; background-color: {status_color}; }}
            .detail-row {{ margin: 10px 0; padding: 10px; background-color: #f8f9fa; border-radius: 4px; }}
            .label {{ font-weight: bold; color: #495057; }}
            .footer {{ padding: 15px 20px; background-color: #f8f9fa; border-radius: 0 0 8px 8px; font-size: 12px; color: #6c757d; text-align: center; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>{status_emoji} MediSupply Alert</h2>
                <p>Service Status Notification</p>
            </div>
            
            <div class="content">
                <div class="detail-row">
                    <span class="label">Service:</span> <strong>{service}</strong>
                </div>
                
                <div class="detail-row">
                    <span class="label">Status:</span> 
                    <span class="status-badge">{status.upper()}</span>
                </div>
                
                <div class="detail-row">
                    <span class="label">Response Time:</span> <strong>{latency_ms}ms</strong>
                </div>
                
                <div class="detail-row">
                    <span class="label">Timestamp:</span> <strong>{readable_time}</strong>
                </div>
                
                <div class="detail-row">
                    <span class="label">Health Check Details:</span><br>
                    • Shallow Health: <strong>HTTP {shallow_status}</strong><br>
                    • Deep Health: <strong>HTTP {deep_status}</strong>
                </div>
            </div>
            
            <div class="footer">
                This is an automated alert from the MediSupply Availability Monitoring System.<br>
                Generated at {readable_time}
            </div>
        </div>
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8082")))
