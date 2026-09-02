FROM python:3.12-slim
WORKDIR /app
COPY FlashControlProxy/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY FlashControlProxy ./FlashControlProxy
CMD ["uvicorn", "FlashControlProxy.app:app", "--host", "0.0.0.0", "--port", "8080"]
