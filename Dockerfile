FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/ gateway/
COPY scripts/ scripts/
COPY buyer_agent/ buyer_agent/

ENV CHECKPOST_DATABASE_URL=sqlite:////data/checkpost.db
VOLUME /data

EXPOSE 8000
CMD ["sh", "-c", "python -m scripts.seed && python -m uvicorn gateway.main:app --host 0.0.0.0 --port 8000"]
