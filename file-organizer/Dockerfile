FROM python:3.12-slim

WORKDIR /app

# Stdlib only: no requirements.txt
COPY filesOrganizer.py library.py service.py /app/
COPY static /app/static

ENV PYTHONUNBUFFERED=1 \
    INPUT_DIR=/input_directory \
    OUTPUT_DIR=/output_parent_directory \
    TRASH_DIR=/trash \
    CONFIG_DIR=/config \
    PORT=8310

EXPOSE 8310

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ['PORT'], timeout=4)"

# Sort loop + dashboard. The plain loop is still available:
#   python filesOrganizer.py /input_directory /output_parent_directory
CMD ["python", "service.py"]
