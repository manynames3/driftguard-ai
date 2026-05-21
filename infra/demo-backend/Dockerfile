FROM public.ecr.aws/lambda/python:3.11

ARG TERRAFORM_VERSION=1.8.5

RUN dnf install -y unzip && \
    curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" -o /tmp/terraform.zip && \
    unzip /tmp/terraform.zip -d /opt/bin && \
    chmod +x /opt/bin/terraform && \
    rm -f /tmp/terraform.zip && \
    dnf clean all

ENV PATH="/opt/bin:${PATH}" \
    TF_IN_AUTOMATION="1" \
    TF_INPUT="0"

COPY requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt --target ${LAMBDA_TASK_ROOT}

COPY driftguard.py demo_scenarios.py lambda_function.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.handler"]
