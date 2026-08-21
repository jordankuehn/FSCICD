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
# Build
# -----------------------------------------------------------------------------
#   1. Copy the project's .vipc into docker/vipm/ (git-ignored — these are large
#      and project-specific). A .vipc that BUNDLES its packages also works, and
#      is required when a project depends on in-house packages published on no
#      VIPM repository: the installer extracts the bundled .vip payloads and
#      prefers them over the public mirrors.
#   2. From the repository root, with Docker in Windows-container mode:
#
#        docker build -f docker/labview-worker.windows.Dockerfile `
#          -t fscicd-labview:2026q3-windows .
#
#   3. Point fscicd.yml at the result:
#
#        labview:
#          image: fscicd-labview:2026q3-windows
#          platform: windows
#
# Expect the build to take a long time and to need several attempts: it installs
# every package with a live headless LabVIEW, and VIPM's engine is fragile when
# cold. The installer logs what failed and why.
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

COPY docker/vipm/ C:/vipm/

RUN if (-not (Get-ChildItem -Path 'C:\vipm' -Filter '*.vipc' -ErrorAction SilentlyContinue)) { `
      throw 'No .vipc found in C:\vipm. Copy the project configuration into docker/vipm/ before building.' `
    }; `
    powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File 'C:\vipm\install-vipc.ps1'

# Every LabVIEW launch headless and activation-free, so tools that start
# LabVIEW.exe directly do not stop at the activation wizard.
ENV LV_RTE_HEADLESS=1

LABEL org.fscicd.worker.platform="windows" `
      org.fscicd.worker.capabilities="mass_compile,vi_analyzer"
