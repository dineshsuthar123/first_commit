FROM amazoncorretto:21.0.8-al2023@sha256:6ae59b15de57a619c309ae7e604a7f3ae37f7459bcf198df8146e0adf0853549 AS java
FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d
COPY --from=java /usr/lib/jvm/java-21-amazon-corretto /opt/java
ENV JAVA_HOME=/opt/java
ENV PATH="/opt/java/bin:${PATH}" PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN python scripts/build_worker.py
CMD ["python", "-m", "pytest", "-q"]
