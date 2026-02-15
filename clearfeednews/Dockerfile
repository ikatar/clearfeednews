FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV BOT_MODE=webhook
ENV PORT=8443

EXPOSE ${PORT}

CMD ["python", "bot.py"]
