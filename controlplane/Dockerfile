FROM python:3.11-slim

RUN useradd --create-home --uid 1000 holdthedoor
WORKDIR /app

COPY holdthedoor ./holdthedoor
COPY controlplane ./controlplane
RUN pip install --no-cache-dir pyyaml

USER holdthedoor
ENV HOLDTHEDOOR_CONTROLPLANE_POLICY_PATH=/etc/holdthedoor/policy.yaml
EXPOSE 8957

ENTRYPOINT ["python", "-m", "controlplane.server"]
