docker rm -f check_print && \
docker build -t check_printer:1.0 . && \
docker run -d -p 9090:8000 -v ./users.db:/app/users.db check_printer:1.0
