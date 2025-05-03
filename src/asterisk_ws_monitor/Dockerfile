FROM redhat/ubi8:8.4-206.1626828523

RUN dnf -y install python39 &&\
    dnf clean all &&\
    mkdir -p /opt/py-phone-caller/{config,py_phone_caller_utils}

COPY asterisk_ws_monitor/asterisk_ws_monitor.py /opt/py-phone-caller/asterisk_ws_monitor.py
COPY requirements.txt /opt/py-phone-caller/requirements.txt
COPY py_phone_caller_utils/caller_configuration.py /opt/py-phone-caller/py_phone_caller_utils/caller_configuration.py
COPY py_phone_caller_utils/db_conn.py /opt/py-phone-caller/py_phone_caller_utils/db_conn.py
RUN pip3 install -r /opt/py-phone-caller/requirements.txt && chown -R daemon.daemon /opt/py-phone-caller

USER daemon

WORKDIR /opt/py-phone-caller
ENTRYPOINT [ "/usr/bin/python3" ]
CMD [ "asterisk_ws_monitor.py" ]