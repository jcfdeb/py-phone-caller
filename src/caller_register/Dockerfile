FROM redhat/ubi8:8.4-206.1626828523

RUN dnf -y install python39 &&\
    dnf clean all &&\
    mkdir -p /opt/py-phone-caller/{config,caller_utils}

ADD call_register/call_register.py /opt/py-phone-caller/call_register.py
ADD requirements.txt /opt/py-phone-caller/requirements.txt
ADD caller_utils/caller_configuration.py /opt/py-phone-caller/caller_utils/caller_configuration.py
RUN pip3 install -r /opt/py-phone-caller/requirements.txt

RUN chown -R daemon.daemon /opt/py-phone-caller

USER daemon

WORKDIR /opt/py-phone-caller
ENTRYPOINT [ "/usr/bin/python3" ]
CMD [ "call_register.py" ]