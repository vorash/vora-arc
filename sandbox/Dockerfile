# ARC program sandbox: Python 3.13, numpy, and the runner. No pip.
FROM python:3.13-slim

RUN python -m pip install --no-cache-dir numpy==2.5.4 \
    && python -m pip uninstall -y pip

# Documents the thread limits for `docker run`. Vora does not apply image ENV,
# so runner.py sets the same variables before it starts the program.
ENV OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

COPY runner.py /opt/vora-arc/runner.py

# Mount points used by Vora: /workspace (rw) and /vora (rw, agent + socket).
RUN mkdir -p /workspace /vora

# Vora binds the sandbox's resolver config over /etc/resolv.conf, so the path
# must exist in the image. It cannot be created with RUN, because Docker
# bind-mounts a read-only resolv.conf into build containers.
COPY resolv.conf /etc/resolv.conf
