FROM python:3.12-alpine

WORKDIR /app

# Copy the source files
COPY ./calculator /app/calculator
COPY ./requirements.txt /app/requirements.txt

# Install dependencies into a virtual environment
RUN python -m venv /app/venv && \
    /app/venv/bin/pip install --no-cache-dir --upgrade -r /app/requirements.txt

# Mark data storage and expose port
VOLUME /app/cache
EXPOSE 8000

ENTRYPOINT ["/app/venv/bin/fastapi"]
CMD ["run", "calculator/main.py"]
