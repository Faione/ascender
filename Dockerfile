# Use the Engine's bundled Dockerfile frontend; no external syntax image is pulled.
ARG BASE_IMAGE=ubuntu:22.04
ARG TORCH_STAGE=torch-install
FROM ${BASE_IMAGE} AS system-deps
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG APT_MIRROR=
ARG PIP_INDEX_URL=https://pypi.org/simple
# The index is persisted in /etc/pip.conf for all current and future users.
# Keep it as an ARG so runtime environment does not mask user/global pip config.
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY scripts/ /usr/local/lib/ascend/
RUN --mount=type=bind,source=config/apt-packages.txt,target=/tmp/apt-packages.txt,readonly \
    bash /usr/local/lib/ascend/install-system.sh

FROM system-deps AS cann
# Separate input directories keep changes to Torch wheels out of CANN's cache key.
RUN --mount=type=bind,source=packages/cann,target=/tmp/cann-packages,readonly \
    bash /usr/local/lib/ascend/install-cann.sh

FROM cann AS cann-only

FROM cann AS torch-install
ARG TORCH_VERSION
ARG TORCH_NPU_VERSION
ARG TORCH_WHEEL_FILE
ARG TORCH_NPU_WHEEL_FILE
RUN --mount=type=bind,source=packages/torch,target=/tmp/torch-packages,readonly \
    --mount=type=bind,source=config/constraints.txt,target=/tmp/user-constraints.txt,readonly \
    bash /usr/local/lib/ascend/install-torch.sh

FROM ${TORCH_STAGE} AS dev-common
ARG TORCH_VERSION=
ARG TORCH_NPU_VERSION=
ARG DEV_WORKDIR=/workspace
RUN --mount=type=bind,source=config,target=/tmp/config,readonly \
    bash /usr/local/lib/ascend/finish-image.sh
WORKDIR ${DEV_WORKDIR}
ENTRYPOINT ["/usr/local/bin/ascend-entrypoint"]
CMD ["/bin/bash"]

FROM dev-common AS npu
ARG INPUT_FINGERPRINT
LABEL org.opencontainers.image.title="Ascend NPU development environment" \
      dev.ascend.target="npu" dev.ascend.input-fingerprint=${INPUT_FINGERPRINT}

FROM dev-common AS simulation
ENV CAMODEL_HOME=/opt/CAModel ASCEND_ENV_MODE=simulation
RUN --mount=type=bind,source=camodel,target=/tmp/camodel-inputs,readonly \
    bash /usr/local/lib/ascend/prepare-simulation.sh
ARG INPUT_FINGERPRINT
LABEL org.opencontainers.image.title="Ascend simulation development environment" \
      dev.ascend.target="simulation" dev.ascend.input-fingerprint=${INPUT_FINGERPRINT}
