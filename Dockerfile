FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends bubblewrap libseccomp2 git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 --user-group isycode \
 && ln -s /usr/local/bin/python3 /usr/bin/python3

WORKDIR /opt/isycode
COPY pyproject.toml README.md* ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN mkdir -p /state && chown isycode:isycode /state
WORKDIR /workspace
USER isycode
ENTRYPOINT ["python3", "-m", "isycode"]
