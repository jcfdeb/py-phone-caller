FROM redhat/ubi8:8.4-206.1626828523

RUN dnf -y install python39 &&\
    dnf clean all &&\
    mkdir -p /opt/py-phone-caller/{config,caller_utils}

ADD asterisk_ws_monitor/asterisk_ws_monitor.py /opt/py-phone-caller/asterisk_ws_monitor.py
ADD requirements.txt /opt/py-phone-caller/requirements.txt
ADD caller_utils/caller_configuration.py /opt/py-phone-caller/caller_utils/caller_configuration.py
ADD caller_utils/db_conn.py /opt/py-phone-caller/caller_utils/db_conn.py
RUN pip3 install -r /opt/py-phone-caller/requirements.txt

RUN chown -R daemon.daemon /opt/py-phone-caller

USER daemon

WORKDIR /opt/py-phone-caller
ENTRYPOINT [ "/usr/bin/python3" ]
CMD [ "asterisk_ws_monitor.py" ]