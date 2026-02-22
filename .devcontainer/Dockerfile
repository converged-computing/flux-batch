FROM fluxrm/flux-sched:noble

LABEL maintainer="Vanessasaurus <@vsoch>"

# Match the default user id for a single system so we aren't root
ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000
ENV USERNAME=${USERNAME}
ENV USER_UID=${USER_UID}
ENV USER_GID=${USER_GID}
USER root
RUN apt-get update && apt-get install -y less python3-pip openssh-client xorg

# Add the group and user that match our ids
RUN groupadd -g ${USER_GID} ${USERNAME} && \
    adduser --disabled-password --uid ${USER_UID} --gid ${USER_GID} --gecos "" ${USERNAME} && \
    echo "${USERNAME} ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers

# Install Python stuffs
RUN python3 -m pip install Cython IPython setuptools rich --break-system-packages
ENV PATH=/home/vscode/.local/bin:$PATH
ENV PYTHONPATH="/usr/lib/flux/python3.12/"
USER $USERNAME

# mock systemd?
RUN git clone https://github.com/gdraheim/docker-systemctl-replacement /tmp/systemctl && \
    cd /tmp/systemctl && \
    sudo cp files/docker/systemctl3.py /usr/bin/systemctl && \
    sudo chmod +x /usr/bin/systemctl
