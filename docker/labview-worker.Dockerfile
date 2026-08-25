# syntax=docker/dockerfile:1.7
# =============================================================================
# FSCICD LabVIEW worker image (Linux)
# =============================================================================
# Extends the official NI headless LabVIEW container. LabVIEW 2026 Q1+ runs
# LabVIEWCLI operations with NO license activation when invoked with -Headless
# (or with LV_RTE_HEADLESS=1 set), which is what this worker relies on for
# Mass Compile and VI Analyzer in CI.
#
# NOTE: The NI base image is multi-gigabyte and is only available/needed on the
# CI runner. Local development of FSCICD uses `runner: mock` and does not build
# or pull this image.
# =============================================================================
ARG LABVIEW_IMAGE=nationalinstruments/labview:2026q3-linux
FROM ${LABVIEW_IMAGE}

# Default every LabVIEW invocation in this container to headless (no activation).
ENV LV_RTE_HEADLESS=1

# Python 3 is used by the FSCICD report/orchestration scripts that run inside
# the worker alongside LabVIEWCLI.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /work

LABEL org.fscicd.worker.platform="linux" \
      org.fscicd.worker.capabilities="mass_compile,vi_analyzer"
