FROM python:3.11-slim

WORKDIR /app

# Install Doppler CLI
RUN apt-get update && apt-get install -y curl && \
    curl -sLf --retry 3 --tlsv1.2 --proto '=https' 'https://cli.doppler.com/install.sh' | sh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD doppler run -- gunicorn app:app --bind 0.0.0.0:$PORT
