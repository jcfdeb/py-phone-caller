FROM fedora:34

RUN dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm &&\
    rpm --import "https://rpmfusion.org/keys?action=AttachFile&do=get&target=RPM-GPG-KEY-rpmfusion-nonfree-fedora-2020" &&\
    dnf install -y ffmpeg python39 python3-pip &&\
    dnf clean all &&\
    mkdir -p /opt/py-phone-caller/{config,py_phone_caller_utils} &&\
    mkdir /opt/py-phone-caller/audio

# ToDo: 'generate_audio/generate_audio.py' now is part of a package -> 'src/py_phone_caller_utils/py_phone_caller_voices/google_gtts.py' 
COPY generate_audio/generate_audio.py /opt/py-phone-caller/generate_audio.py 
COPY requirements.txt /opt/py-phone-caller/requirements.txt
COPY py_phone_caller_utils/caller_configuration.py /opt/py-phone-caller/py_phone_caller_utils/caller_configuration.py
COPY py_phone_caller_utils/google_voice.py /opt/py-phone-caller/py_phone_caller_utils/google_voice.py
RUN pip3 install -r /opt/py-phone-caller/requirements.txt && chown -R daemon.daemon /opt/py-phone-caller

USER daemon

WORKDIR /opt/py-phone-caller
ENTRYPOINT [ "/usr/bin/python3" ]
CMD [ "generate_audio.py" ]