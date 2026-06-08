FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ ./src/

WORKDIR /app/src

EXPOSE 8000

CMD ["uvicorn", "main:TurtleNet", "--host", "0.0.0.0", "--port", "8000"]