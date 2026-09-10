# Test-only image: same application/runtime as the candidate, plus pytest.
# Do not use this image for deployment.
ARG DOCUMENT_IMAGE=aicommander-backend-documents:v4.1-candidate
FROM ${DOCUMENT_IMAGE}
USER root
RUN pip install --no-cache-dir pytest==9.1.1
USER 10001:10001
