FROM python:3.11-slim

RUN useradd --create-home --uid 1000 privacyhook
WORKDIR /app

COPY privacyhook ./privacyhook
COPY controlplane ./controlplane
RUN pip install --no-cache-dir pyyaml

USER privacyhook
ENV PRIVACYHOOK_CONTROLPLANE_POLICY_PATH=/etc/privacyhook/policy.yaml
EXPOSE 8957

ENTRYPOINT ["python", "-m", "controlplane.server"]
