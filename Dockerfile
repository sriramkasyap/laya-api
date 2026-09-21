FROM python:3.11-slim

WORKDIR /app
ENV HF_HOME=/models PYTHONUNBUFFERED=1

# CPU-only torch keeps the image ~2GB smaller; drop --index-url for a CUDA host
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8008
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8008/health')"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8008"]
