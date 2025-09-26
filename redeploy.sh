docker rm -f check_print && \
docker build -t check_printer:1.0 . && \
docker run --name check_print \
  -d -p 9090:8000 \
  -v "$(pwd)/data:/app/data" \
  check_printer:1.0