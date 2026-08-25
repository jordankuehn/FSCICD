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
# IMPORTANT: VIPM cannot currently install anything in this image at all
# -----------------------------------------------------------------------------
# Not a build-vs-run problem, and not a window-station problem: the same failure
# occurs under `docker run`. The VIPM CLI reaches VIPM by launching
# "VIPM File Handler.exe" against a pair of temp files, and in NI's 2026 Windows
# container that LabVIEW-built helper dies with 0xC0000005 about two seconds in,
# before writing its return file. The CLI then polls for a file that will never
# appear until the operation times out ("wait for VIPM startup").
#
# So this Dockerfile deliberately does NOT run the installer; it only stages the
# tooling, and install-vipc.ps1 checks that hop up front and fails in seconds
# with the real reason. See docker/README.md for the full evidence.
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
#
# Note this also puts VIPM's LabVIEW-built helpers into 2026's headless run mode,
# which turns their .NET load fault into a hard 0xC0000005 instead of a silent
# clean exit. It is not the cause — they fail to answer either way — so the
# variable stays for LabVIEWCLI's sake.
ENV LV_RTE_HEADLESS=1

LABEL org.fscicd.worker.platform="windows" `
      org.fscicd.worker.capabilities="mass_compile,vi_analyzer"
