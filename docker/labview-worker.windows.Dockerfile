# escape=`
# =============================================================================
# FSCICD LabVIEW worker image (Windows)
# =============================================================================
# The stock NI image runs LabVIEW headlessly but knows nothing about a project's
# VIPM add-ons, so a real project's VIs load broken: LabVIEW finds each VI and
# cannot resolve its subVIs. Measurements against a 1642-VI project needing 148
# packages put only 207 VIs (13%) analyzable on the stock image, and mounting a
# developer machine's vi.lib/user.lib/instr.lib raised that only to 255 — a file
# copy is not an install, which also performs registry, Settings.ini and palette
# registration.
#
# This image installs the packages properly, with VIPM, at build time.
#
# The base image, the VIPM-in-a-container technique, and the workarounds in
# vipm/install-vipc.ps1 come from Elijah Kerry's LabVIEW-CI-with-Containers
# (https://github.com/elijah286/LabVIEW-CI-with-Containers), used with the
# author's permission.
#
# -----------------------------------------------------------------------------
# IMPORTANT: `docker build` cannot install the packages
# -----------------------------------------------------------------------------
# The VIPM CLI delegates to an engine that is a LabVIEW-runtime GUI application.
# Under `docker run` it starts and reports Responding within a minute; under
# `docker build` it never completes its startup handshake, and every VIPM call
# fails with "Operation 'wait for VIPM startup' timed out" after the full
# timeout. Windows build steps run their children on a non-interactive window
# station, which the engine evidently cannot use.
#
# So this Dockerfile deliberately does NOT run the installer. It only stages the
# tooling. The packages are installed by running a container and committing it —
# see docker/README.md for the two commands.
# =============================================================================

# The LCWC base adds VI Analyzer support, the NI Unit Test Framework, VIPM and
# git to NI's image — all of which the stock image lacks. Step 2 of the plan is
# to build an equivalent base locally from nationalinstruments/labview:*-windows
# so nothing depends on a third party's registry.
ARG LCWC_BASE_IMAGE=ghcr.io/elijah286/labview-ci-with-containers-labview-base:2026
FROM ${LCWC_BASE_IMAGE}

SHELL ["powershell", "-NoLogo", "-NoProfile", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]

# Must match the LabVIEW in the base image, or `vipm install` targets nothing.
ARG LABVIEW_VERSION=2026
ARG LABVIEW_BITNESS=64
ENV LABVIEW_VERSION=${LABVIEW_VERSION} `
    LABVIEW_BITNESS=${LABVIEW_BITNESS}

# Staged, not executed. The installer runs later in a container, because a build
# step cannot start the VIPM engine (see the note above).
COPY docker/vipm/ C:/vipm/

RUN if (-not (Get-ChildItem -Path 'C:\vipm' -Filter '*.vipc' -ErrorAction SilentlyContinue)) { `
      throw 'No .vipc found in C:\vipm. Copy the project configuration into docker/vipm/ before building.' `
    }; `
    Write-Host 'Staged the VIPM tooling. Run docker/README.md''s install step to bake the packages in.'

# Every LabVIEW launch headless and activation-free, so tools that start
# LabVIEW.exe directly do not stop at the activation wizard.
ENV LV_RTE_HEADLESS=1

LABEL org.fscicd.worker.platform="windows" `
      org.fscicd.worker.capabilities="mass_compile,vi_analyzer"
