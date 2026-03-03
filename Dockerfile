FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["python", "-c", "import os, subprocess; port = os.environ.get('PORT', '8080'); subprocess.run(['gunicorn', 'app:app', '--bind', f'0.0.0.0:{port}', '--timeout', '120'])"]
