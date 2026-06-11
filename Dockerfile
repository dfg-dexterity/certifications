FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY sync_service/ sync_service/
ENV PYTHONPATH=/app/sync_service \
    PYTHONUNBUFFERED=1

# Roda continuamente a cada 15 minutos (seção 12 da especificação).
CMD ["python", "-m", "jira_odoo_sync", "sync", "--loop", "--interval", "900"]
