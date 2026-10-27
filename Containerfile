# Heirloom — a glossy, touch-first Linux for 2-in-1 tablets.
#
# This file is the whole operating system recipe. It starts from Fedora
# Silverblue (Fedora's image-based GNOME edition) and adds Heirloom's apps,
# look and settings on top. GitHub builds it automatically; see the README.
#
# To move to a newer Fedora, change FEDORA_VERSION below.

ARG FEDORA_VERSION=44

FROM scratch AS ctx
COPY build_files /build_files
COPY system_files /system_files
COPY apps /apps

FROM quay.io/fedora/fedora-silverblue:${FEDORA_VERSION}

ARG FEDORA_VERSION
RUN --mount=type=bind,from=ctx,source=/,target=/ctx \
    --mount=type=cache,dst=/var/cache \
    --mount=type=tmpfs,dst=/tmp \
    FEDORA_VERSION=${FEDORA_VERSION} bash /ctx/build_files/build.sh

# Catches mistakes that would make the image fail to boot or update.
RUN bootc container lint
