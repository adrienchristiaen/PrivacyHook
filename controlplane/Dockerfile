FROM python:3.11-slim

RUN useradd --create-home --uid 1000 privacyhook
WORKDIR /app

COPY privacyhook ./privacyhook
COPY controlplane ./controlplane
# psycopg is only used when PRIVACYHOOK_CONTROLPLANE_DATABASE_URL points at Postgres.
RUN pip install --no-cache-dir pyyaml "psycopg[binary]>=3.1"

RUN mkdir /data && chown privacyhook /data
USER privacyhook
# The policy file is optional: without it the server starts with no central
# rules and only collects activity for the dashboard.
ENV PRIVACYHOOK_CONTROLPLANE_POLICY_PATH=/etc/privacyhook/policy.yaml
ENV PRIVACYHOOK_CONTROLPLANE_DB=/data/events.db
VOLUME /data
EXPOSE 8957

ENTRYPOINT ["python", "-m", "controlplane.server"]
