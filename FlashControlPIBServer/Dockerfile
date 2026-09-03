FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

RUN addgroup --system flashcontrol \
    && adduser --system --ingroup flashcontrol --no-create-home flashcontrol \
    && chown -R flashcontrol:flashcontrol /app

USER flashcontrol

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=4 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
