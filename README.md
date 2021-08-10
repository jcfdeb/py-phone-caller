[![SL Scan](https://github.com/jcfdeb/py-phone-caller/actions/workflows/shiftleft-analysis.yml/badge.svg)](https://github.com/jcfdeb/py-phone-caller/actions/workflows/shiftleft-analysis.yml)


# py-phone-caller

> If you've love for yourself and your team, right now this project isn't ready yet for production. 
> different blocks of coded need to be improved also some unused lines removed...

> More content is coming soon... (also the setup documentation)

**Note**: please, consider that it will not work without setting up a lot of things :) 

*Without the intention to be the replacement of PagerDuty or other services like it... here we go!*


### In few words 

Through the Asterisk Rest Interface, Google TTS (**gtts**) and Twilio this set of scripts send a text message 
and/or place a call when the Prometheus Alertmanager calls the '*caller_prometheus_webhook.py*'.

Also is possible send a text message (SMS) or place a call to a given phone number through 'caller_sms.py' 
and 'asterisk_call.py'. 

Within the main use case, you can configure the system to make 'n' number of calls in a given period of time 
(*3 reties in 300 seconds is a good compromise...*). During the call, the callee, is asked to press a number in order to 
acknowledge the message (by default the number '4'). When there's no acknowledgement, the system will retry the 'n' times
in the given period of time.


### What we need to make it work...

* A Twilio account (used by send the SMS text messages)
* A working Asterisk PBX with some trunk configured in order to place calls
* A PostgreSQL (>= 9) instance
* Run as a Systemd service or as containers (*can be deployed in Kubernetes, with the **Asterisk PBX outside of K8S***)  
* A lot of patience 


### The main group of files  

Needed to get it up and running 

```
├── config/
│   └── caller_config.toml
│
├── local_utils/
│   ├── caller_configuration.py
│   ├── db_conn.py
│   ├── google_voice.py
│   └── sms
│       │
│       └── twilio_sms.py
├── caller_prometheus_webhook.py
├── caller_sms.py
├── generate_audio.py
├── call_register.py
├── asterisk_ws_monitor.py
├── asterisk_recall.py
├── asterisk_call.py
```
* Last tree but not least 

The files to be imported into the PostgreSQL server

``psql -f the_file.sql ...``

```
├── assets
│      ├── DB
│      │    ├── db-role.sql
│      │    └── db-schema.sql
```
