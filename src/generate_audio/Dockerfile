FROM fedora:34

RUN dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm &&\
    rpm --import "https://rpmfusion.org/keys?action=AttachFile&do=get&target=RPM-GPG-KEY-rpmfusion-nonfree-fedora-2020" &&\
    dnf install -y ffmpeg python39 python3-pip &&\
    dnf clean all &&\
    mkdir -p /opt/py-phone-caller/{config,caller_utils} &&\
    mkdir /opt/py-phone-caller/audio

ADD generate_audio/generate_audio.py /opt/py-phone-caller/generate_audio.py
ADD requirements.txt /opt/py-phone-caller/requirements.txt
ADD caller_utils/caller_configuration.py /opt/py-phone-caller/caller_utils/caller_configuration.py
ADD caller_utils/google_voice.py /opt/py-phone-caller/caller_utils/google_voice.py
RUN pip3 install -r /opt/py-phone-caller/requirements.txt

RUN chown -R daemon.daemon /opt/py-phone-caller

USER daemon

WORKDIR /opt/py-phone-caller
ENTRYPOINT [ "/usr/bin/python3" ]
CMD [ "generate_audio.py" ]