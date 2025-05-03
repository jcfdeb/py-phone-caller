FROM redhat/ubi8:8.4-206.1626828523

RUN dnf -y install python39 &&\
    dnf clean all &&\
    mkdir -p /opt/py-phone-caller/{config,py_phone_caller_utils}

COPY asterisk_caller/asterisk_caller.py /opt/py-phone-caller/asterisk_caller.py
COPY requirements.txt /opt/py-phone-caller/requirements.txt
COPY py_phone_caller_utils/caller_configuration.py /opt/py-phone-caller/py_phone_caller_utils/caller_configuration.py
RUN pip3 install -r /opt/py-phone-caller/requirements.txt && chown -R daemon.daemon /opt/py-phone-caller
    
USER daemon

WORKDIR /opt/py-phone-caller
ENTRYPOINT [ "/usr/bin/python3" ]
CMD [ "asterisk_caller.py" ]