FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends adb && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY android_test_server.py /app/android_test_server.py
EXPOSE 8080
CMD ["python","-u","android_test_server.py"]
