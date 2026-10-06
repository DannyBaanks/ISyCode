FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends bubblewrap libseccomp2 git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/isycode
COPY pyproject.toml README.md* ./
COPY src ./src
RUN pip install --no-cache-dir .

WORKDIR /workspace
ENTRYPOINT ["python3", "-m", "isycode"]
