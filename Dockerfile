FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD gunicorn server:app --workers 1 --threads 4 --bind 0.0.0.0:$PORT --timeout 120
