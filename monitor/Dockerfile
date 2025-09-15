FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY monitor_local.py .
COPY targets.yaml .
COPY targets-aws.yaml .
CMD ["python", "monitor_local.py"]
