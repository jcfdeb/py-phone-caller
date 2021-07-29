# Work in Progress - Draft

In this use case we assume that: the system is inside a LAN and protected by a firewall without allowing connections 
from outside (*wee need to protect in some way, for example basic auth, the exposed services if we want to publish it 
in the Internet*) 

### Configuration of the Asterisk PBX

* Configuration of the **SIP** Trunk
![trunk configuration step 1](freepbx-setup/image/trunk/trunk-01.png "Trunk configuration")

![trunk configuration step 2](freepbx-setup/image/trunk/trunk-02.png "Trunk configuration")

![trunk configuration step 3](freepbx-setup/image/trunk/trunk-03.png "Trunk configuration")

![trunk configuration step 4](freepbx-setup/image/trunk/trunk-04.png "Trunk configuration")

![trunk configuration step 5](freepbx-setup/image/trunk/trunk-05.png "Trunk configuration")

![trunk configuration step 6](freepbx-setup/image/trunk/trunk-06.png "Trunk configuration")


* Configuration of the custom **SIP extension**

![SIP extension step 1](freepbx-setup/image/custom_extension/ediit_custom_exten-01.png "SIP custom extension")

![SIP extension step 2](freepbx-setup/image/custom_extension/ediit_custom_exten-02.png "SIP custom extension")

![SIP extension step 3](freepbx-setup/image/custom_extension/ediit_custom_exten-03.png "SIP custom extension")

![SIP extension step 4](freepbx-setup/image/custom_extension/ediit_custom_exten-04.png "SIP custom extension")

![SIP extension step 5](freepbx-setup/image/custom_extension/ediit_custom_exten-05.png "SIP custom extension")


* Configuration of the Asterisk **ARI** user

![ARI user step 1](freepbx-setup/image/rest_interface_user/rest_interface_user-01.png "The ARI user for our Stasis app")

![ARI user step 2](freepbx-setup/image/rest_interface_user/rest_interface_user-02.png "The ARI user for our Stasis app")

![ARI user step 3](freepbx-setup/image/rest_interface_user/rest_interface_user-03.png "The ARI user for our Stasis app")

![ARI user step 4](freepbx-setup/image/rest_interface_user/rest_interface_user-04.png "The ARI user for our Stasis app")

![ARI user step 5](freepbx-setup/image/rest_interface_user/rest_interface_user-05.png "The ARI user for our Stasis app")


* Copying the audio files used en the custom extension

> Work in progress

### Installing the needed dependencies on the Fedora Server

Steps to take as '**root**'

```
[fedora@fedora-server ~]$ sudo -i
```

We'll run the containers with **'Podman'**
```
[root@fedora-server ~]# dnf -y install podman podman-plugins podman-docker
Last metadata expiration check: 0:42:59 ago on Wed 28 Jul 2021 23:31:23 PM CEST.
Dependencies resolved.
=============================================================================================================================================================================
 Package                                            Architecture                  Version                                               Repository                      Size
=============================================================================================================================================================================
Installing:
 podman                                             x86_64                        3:3.2.3-1.fc34                                        updates                         12 M
 podman-docker                                      noarch                        3:3.2.3-1.fc34                                        updates                        177 k
 podman-plugins                                     x86_64                        3:3.2.3-1.fc34                                        updates                        2.6 M
Installing dependencies:
 conmon                                             x86_64                        2:2.0.29-2.fc34                                       updates                         53 k
 container-selinux                                  noarch                        2:2.164.1-1.git563ba3f.fc34                           updates                         48 k
 containernetworking-plugins                        x86_64                        1.0.0-0.2.rc1.fc34                                    updates                        8.9 M
 containers-common                                  noarch                        4:1-21.fc34                                           updates                         61 k
 criu                                               x86_64                        3.15-3.fc34                                           fedora                         521 k
 criu-libs                                          x86_64                        3.15-3.fc34                                           fedora                          31 k
 crun                                               x86_64                        0.20.1-1.fc34                                         updates                        172 k
 fuse-common                                        x86_64                        3.10.4-1.fc34                                         updates                        8.5 k
 fuse3                                              x86_64                        3.10.4-1.fc34                                         updates                         54 k
 fuse3-libs                                         x86_64                        3.10.4-1.fc34                                         updates                         91 k
 libbsd                                             x86_64                        0.10.0-7.fc34                                         fedora                         106 k
 libnet                                             x86_64                        1.2-2.fc34                                            fedora                          58 k
 libslirp                                           x86_64                        4.4.0-4.fc34                                          updates                         68 k
 yajl                                               x86_64                        2.1.0-16.fc34                                         fedora                          38 k
Installing weak dependencies:
 catatonit                                          x86_64                        0.1.5-4.fc34                                          fedora                         305 k
 fuse-overlayfs                                     x86_64                        1.5.0-1.fc34                                          fedora                          75 k
 slirp4netns                                        x86_64                        1.1.9-1.fc34                                          fedora                          57 k

Transaction Summary
=============================================================================================================================================================================
Install  20 Packages

Total download size: 25 M
Installed size: 123 M
[...]
```

The installation of '**py-phone-caller**' is done through **Ansible** and some data regarding the call is stored in 
**PostgreSQL**.

```
[root@fedora-server ~]# dnf install -y ansible python3-psycopg2 postgresql
Last metadata expiration check: 0:38:54 ago on Wed 28 Jul 2021 23:41:48 PM CEST.
Dependencies resolved.
=============================================================================================================================================================================
 Package                                           Architecture                       Version                                      Repository                           Size
=============================================================================================================================================================================
Installing:
 ansible                                           noarch                             2.9.23-1.fc34                                updates                              15 M
 python3-psycopg2                                  x86_64                             2.8.6-3.fc34                                 fedora                              183 k
Installing dependencies:
 libpq                                             x86_64                             13.3-1.fc34                                  updates                             202 k
 libsodium                                         x86_64                             1.0.18-7.fc34                                fedora                              165 k
 python3-babel                                     noarch                             2.9.1-1.fc34                                 updates                             5.8 M
 python3-bcrypt                                    x86_64                             3.1.7-7.fc34                                 fedora                               44 k
 python3-cffi                                      x86_64                             1.14.5-1.fc34                                fedora                              244 k
 python3-chardet                                   noarch                             4.0.0-1.fc34                                 fedora                              214 k
 python3-cryptography                              x86_64                             3.4.6-1.fc34                                 fedora                              1.4 M
 python3-idna                                      noarch                             2.10-3.fc34                                  fedora                               99 k
 python3-jinja2                                    noarch                             2.11.3-1.fc34                                fedora                              493 k
 python3-jmespath                                  noarch                             0.10.0-1.fc34                                updates                              46 k
 python3-markupsafe                                x86_64                             1.1.1-10.fc34                                fedora                               32 k
 python3-ntlm-auth                                 noarch                             1.5.0-2.fc34                                 fedora                               53 k
 python3-ply                                       noarch                             3.11-11.fc34                                 fedora                              103 k
 python3-pycparser                                 noarch                             2.20-3.fc34                                  fedora                              126 k
 python3-pynacl                                    x86_64                             1.4.0-2.fc34                                 fedora                              110 k
 python3-pysocks                                   noarch                             1.7.1-8.fc34                                 fedora                               35 k
 python3-pytz                                      noarch                             2021.1-2.fc34                                fedora                               49 k
 python3-pyyaml                                    x86_64                             5.4.1-2.fc34                                 fedora                              194 k
 python3-requests                                  noarch                             2.25.1-1.fc34                                fedora                              114 k
 python3-requests_ntlm                             noarch                             1.1.0-14.fc34                                fedora                               18 k
 python3-urllib3                                   noarch                             1.25.10-5.fc34                               updates                             174 k
 python3-xmltodict                                 noarch                             0.12.0-11.fc34                               fedora                               23 k
 sshpass                                           x86_64                             1.09-1.fc34                                  fedora                               27 k
Installing weak dependencies:
 python3-paramiko                                  noarch                             2.7.2-4.fc34                                 fedora                              287 k
 python3-pyasn1                                    noarch                             0.4.8-4.fc34                                 fedora                              133 k
 python3-winrm                                     noarch                             0.4.1-2.fc34                                 fedora                               79 k

Transaction Summary
=============================================================================================================================================================================
Install  28 Packages

Total download size: 25 M
Installed size: 144 M

[...]
```

Dropping the '**root**' privileges

```
[root@fedora-server ~]# 
logout
```

Installing the **Ansible** role to manage '**podman**'

```
[fedora@fedora-server ~]$ ansible-galaxy collection install containers.podman
Process install dependency map
Starting collection install process
Installing 'containers.podman:1.6.1' to '/home/fedora/.ansible/collections/ansible_collections/containers/podman'
```

Installing the **Ansible** role to manage '**PostgreSQL**'

```
[fedora@fedora-server ~]$ ansible-galaxy collection install community.postgresql
Process install dependency map
Starting collection install process
Installing 'community.postgresql:1.4.0' to '/home/fedora/.ansible/collections/ansible_collections/community/postgresql'
```



Running our first container... 
```
[fedora@fedora-server ~]$ podman run hello-world
Resolved "hello-world" as an alias (/etc/containers/registries.conf.d/000-shortnames.conf)
Trying to pull docker.io/library/hello-world:latest...
Getting image source signatures
Copying blob b8dfde127a29 done  
Copying config d1165f2212 done  
Writing manifest to image destination
Storing signatures

Hello from Docker!
This message shows that your installation appears to be working correctly.

To generate this message, Docker took the following steps:
 1. The Docker client contacted the Docker daemon.
 2. The Docker daemon pulled the "hello-world" image from the Docker Hub.
    (amd64)
 3. The Docker daemon created a new container from that image which runs the
    executable that produces the output you are currently reading.
 4. The Docker daemon streamed that output to the Docker client, which sent it
    to your terminal.

To try something more ambitious, you can run an Ubuntu container with:
 $ docker run -it ubuntu bash

Share images, automate workflows, and more with a free Docker ID:
 https://hub.docker.com/

For more examples and ideas, visit:
 https://docs.docker.com/get-started/
```


Creating a folder to place the installation *playbook*

```
[fedora@fedora-server ~]$ mkdir ansible_py-phone-caller
```


Getting the 3 files in order to install the '**py-phone-caller**' through **Ansible**

    * caller_config.toml.jinja2
    * py-phone-caller-podman.yml
    * py_phone_caller_vars_file.yml


```
[fedora@fedora-server ~]$ cd ansible_py-phone-caller/

[fedora@fedora-server ansible_py-phone-caller]$ wget https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/ansible/rh/caller_config.toml.jinja2
--2021-07-28 23:48:11--  https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/ansible/rh/caller_config.toml.jinja2
Resolving raw.githubusercontent.com (raw.githubusercontent.com)... 185.199.108.133, 185.199.109.133, 185.199.110.133, ...
Connecting to raw.githubusercontent.com (raw.githubusercontent.com)|185.199.108.133|:443... connected.
HTTP request sent, awaiting response... 200 OK
Length: 3730 (3.6K) [text/plain]
Saving to: ‘caller_config.toml.jinja2’

caller_config.toml.jinja2                   100%[========================================================================================>]   3.64K  --.-KB/s    in 0s      

2021-07-28 23:48:11 (20.4 MB/s) - ‘caller_config.toml.jinja2’ saved [3730/3730]



[fedora@fedora-server ansible_py-phone-caller]$ wget https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/ansible/rh/py-phone-caller-podman.yml
--2021-07-28 23:49:55--  https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/ansible/rh/py-phone-caller-podman.yml
Resolving raw.githubusercontent.com (raw.githubusercontent.com)... 185.199.109.133, 185.199.108.133, 185.199.111.133, ...
Connecting to raw.githubusercontent.com (raw.githubusercontent.com)|185.199.109.133|:443... connected.
HTTP request sent, awaiting response... 200 OK
Length: 10793 (11K) [text/plain]
Saving to: ‘py-phone-caller-podman.yml’

py-phone-caller-podman.yml                  100%[========================================================================================>]  10.54K  --.-KB/s    in 0s      

2021-07-28 23:49:55 (25.7 MB/s) - ‘py-phone-caller-podman.yml’ saved [10793/10793]


[fedora@fedora-server ansible_py-phone-caller]$ wget https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/ansible/rh/py_phone_caller_vars_file.yml
--2021-07-28 23:51:20--  https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/ansible/rh/py_phone_caller_vars_file.yml
Resolving raw.githubusercontent.com (raw.githubusercontent.com)... 185.199.111.133, 185.199.110.133, 185.199.109.133, ...
Connecting to raw.githubusercontent.com (raw.githubusercontent.com)|185.199.111.133|:443... connected.
HTTP request sent, awaiting response... 200 OK
Length: 7149 (7.0K) [text/plain]
Saving to: ‘py_phone_caller_vars_file.yml’

py_phone_caller_vars_file.yml               100%[========================================================================================>]   6.98K  --.-KB/s    in 0s      

2021-07-28 23:51:20 (14.6 MB/s) - ‘py_phone_caller_vars_file.yml’ saved [7149/7149]
```



* The varialbes file 'py_phone_caller_vars_file.yml'



```yaml
---
# Variables files for the 'py-phone-caller' installed through Podman

ansible_python_interpreter: /usr/bin/python3

# Podman / 'py-phone-caller' vars
container_host: 192.168.122.105
installation_user: fedora
installation_folder: "/home/{{ installation_user }}"
installation_folder_name: py-phone-caller
caller_config_toml_template_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/9c0bb97110cef988adfd23a6c0cb8e25168bbdfc/assets/ansible/rh/caller_config.toml.jinja2"
py_phone_caller_config_tmp_path: /tmp/caller_config.toml.jinja
py_phone_caller_config_path: "{{ installation_folder }}/{{ installation_folder_name }}/config/caller_config.toml"
config_mounted_in_container: /opt/py-phone-caller/config/caller_config.toml:Z
py_phone_caller_version: 0.0.1
container_registry_url: quay.io/py-phone-caller
py_phone_caller_network: py-phone-caller
py_phone_caller_subnet: 172.19.0.0/24
asterisk_ws_monitor_ip: 172.19.0.10
asterisk_recall_ip: 172.19.0.11
postgres_ip: 172.19.0.50
generate_audio_ip: 172.19.0.82
call_register_ip: 172.19.0.83
asterisk_call_ip: 172.19.0.81
caller_prometheus_webhook_ip: 172.19.0.84
caller_sms_ip: 172.19.0.85

# PostgreSQL container vars
db_schema_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/DB/db-schema.sql"
postgresql_container_image: "docker.io/library/postgres:13.3-alpine3.14"
postgresql_login_host: 127.0.0.1
postgresql_admin: postgres
postgresql_admin_pass: Use-A-Secure-Password-Here

# SystemD user integration
container_asterisk_call_service_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-asterisk_call.service"
container_asterisk_call_register_service_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-asterisk_call_register.service"
container_asterisk_recall_service_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-asterisk_recall.service"
container_asterisk_ws_monitor_service_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-asterisk_ws_monitor.service"
container_caller_prometheus_webhook_service_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-caller_prometheus_webhook.service"
container_caller_sms_service_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-caller_sms.service"
container_generate_audio_service_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-generate_audio.service"
container_postgres_13_service_url: "https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-postgres_13.service"

systemd_user_path: "/home/{{ installation_user }}/.config/systemd/user"
container_asterisk_call_service_unit: "container-asterisk_call.service"
container_asterisk_call_register_service_unit: "container-asterisk_call_register.service"
container_asterisk_recall_service_unit: "container-asterisk_recall.service"
container_asterisk_ws_monitor_service_unit: "container-asterisk_ws_monitor.service"
container_caller_prometheus_webhook_service_unit: "container-caller_prometheus_webhook.service"
container_caller_sms_service_unit: "container-caller_sms.service"
container_generate_audio_service_unit: "container-generate_audio.service"
container_postgres_13_service_unit: "container-postgres_13.service"

# py-phone-caller - 'caller_config.toml' vars
# [commons]
asterisk_user: "py-phone-caller"
asterisk_pass: "Use-A-Secure-Password-Here"
asterisk_host: "192.168.122.234"
asterisk_web_port: "8088"
asterisk_http_scheme: "http"

# [asterisk_call]
asterisk_ari_channels: "ari/channels"
asterisk_ari_play: "play?media=sound"
asterisk_context: "py-phone-caller"
asterisk_extension: "3216"
asterisk_chan_type: "SIP/sip-provider"
asterisk_callerid: "Py-Phone-Caller"
asterisk_call_http_scheme: "http"
asterisk_call_host: "{{ container_host }}"
asterisk_call_port: "8081"
asterisk_call_app_route_asterisk_init: "asterisk_init"
asterisk_call_app_route_play: "play"
seconds_to_forget: 300
client_timeout_total: 5 # For 'ClientTimeout(total=5)'

# [call_register]
call_register_http_scheme: "http"
call_register_host: "{{ container_host }}"
call_register_port: "8083"
call_register_app_route_register_call: "register_call"
call_register_app_route_voice_message: "msg"
call_register_app_route_acknowledge: "ack"
call_register_app_route_heard: "heard"

# [asterisk_ws_monitor]
asterisk_stasis_app: "py-phone-caller"

# [asterisk_recall]
times_to_dial: 3

# [generate_audio]
generate_audio_http_scheme: "http"
generate_audio_host: "{{ container_host }}"
generate_audio_port: "8082"
generate_audio_app_route: "make_audio"
gcloud_tts_language_code: "es"
serving_audio_folder: "audio"
num_of_cpus: 4

# [caller_prometheus_webhook]
prometheus_webhook_port: "8084"
prometheus_webhook_app_route_call_only: "call_only"
prometheus_webhook_app_route_sms_only: "sms_only"
prometheus_webhook_app_route_sms_before_call: "sms_before_call"
prometheus_webhook_app_route_call_and_sms: "call_and_sms"
prometheus_webhook_receivers: '[ "+123456789" ]'

# [caller_sms]
caller_sms_http_scheme: "http"
caller_sms_host: "{{ container_host }}"
caller_sms_port: "8085"
caller_sms_audio_app_route: "send_sms"
sms_before_call_wait_seconds: 120
caller_sms_carrier: "twilio"
twilio_account_sid: "Your-Twilio-account-sid"
twilio_auth_token: "Your-Twilio-auth-token"
twilio_sms_from: "+1987654321"

# [database]
db_host: "{{ postgres_ip }}"
db_name: "py_phone_caller"
db_user: "py_phone_caller"
db_password: 'Use-A-Secure-Password-Here'
db_max_size: 50
db_max_inactive_connection_lifetime: 30.0

# [logger]
log_formatter: "%(asctime)s %(message)s"
acknowledge_error: "Lost parameter, Usage: Method: POST - http://ADDRESS/ack?asterisk_chan=[The Asterisk Channel ID]"
heard_error: "Lost parameter, Usage: Method: POST - http://ADDRESS/heard?asterisk_chan=[The Asterisk Channel ID]"
registercall_error: "Lost parameter, Usage: Method: POST - http://ADDRESS/?phone=[Destination Phone Number]&messagge=[Alert Message Text]&asterisk_chan=[The Asterisk Channel ID]"
voice_message_error: "Lost parameter, Usage: Method: POST - http://ADDRESS/msg?asterisk_chan=[The Asterisk Channel ID]"
asterisk_call_error: "Lost parameter, Usage: Method: POST - http://ADDRESS/asterisk?phone=[Destination Phone Number]&messagge=[Alert Message Text]"
asterisk_play_error: "Lost parameter, Usage: Method: POST - http://ADDRESS/play?asterisk_chan=[The Asterisk Channel ID]&msg_chk_sum=[The message cecksum]"
generate_audio_error: "Lost parameter, Usage: Method: POST - http://ADDRESS/make_audio?messagge=[Alert Message Text]&msg_chk_sum=[The message cecksum]"
caller_sms_error: "Lost parameter, Usage: Method: POST - http://ADDRESS/?phone=[Destination Phone Number]&messagge=[Alert Message Text]"
lost_directory_error: "The folder to serve the audio files was not found."
```

* Ansible starts to play 

```
[fedora@fedora ~]$ ansible-playbook --connection=local --limit=127.0.0.1 --inventory=127.0.0.1, ansible_py-phone-caller/py-phone-caller-podman.yml

PLAY [Configuring 'py-phone-caller' installed through 'Podman'] *************************************************************************************************************

TASK [Gathering Facts] ******************************************************************************************************************************************************
ok: [127.0.0.1]

TASK [Creating the 'py-phone-caller' directory tree at '/home/fedora/py-phone-caller'] **************************************************************************************
changed: [127.0.0.1]

TASK [Check that the 'caller_config.toml' exists] ***************************************************************************************************************************
ok: [127.0.0.1]

TASK [Download the 'caller_config.toml' template file] **********************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the configuration file 'caller_config.toml' through a template] **********************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'py-phone-caller' container network] *********************************************************************************************************************
changed: [127.0.0.1]

TASK [Checking if the 'pgdata' volume exists] *******************************************************************************************************************************
fatal: [127.0.0.1]: FAILED! => {"changed": true, "cmd": ["podman", "volume", "inspect", "pgdata"], "delta": "0:00:00.059469", "end": "2021-07-28 22:04:44.174686", "msg": "non-zero return code", "rc": 125, "start": "2021-07-28 22:04:44.115217", "stderr": "Error: error inspecting object: no such volume pgdata", "stderr_lines": ["Error: error inspecting object: no such volume pgdata"], "stdout": "[]", "stdout_lines": ["[]"]}

TASK [Creating the 'pgdata' volume for the PostgreSQL container] ************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'postgres_13' container] *********************************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'asterisk_call' container] *******************************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'caller_prometheus_webhook' container] *******************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'caller_sms' container] **********************************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'generate_audio' container] ******************************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'py_phone_caller' PostgreSQL user] ***********************************************************************************************************************
changed: [127.0.0.1]

TASK [Gattering info about the 'py_phone_caller' DB (if exists)] ************************************************************************************************************
fatal: [127.0.0.1]: FAILED! => {"changed": false, "msg": "unable to connect to database: FATAL:  database \"py_phone_caller\" does not exist\n"}

TASK [Download the dumped 'py_phone_caller' DB schema (SQL format)] *********************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'py_phone_caller' DB] ************************************************************************************************************************************
changed: [127.0.0.1]

TASK [Restoring the 'py_phone_caller' DB by restoring a dump of the schema] *************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'asterisk_ws_monitor' container] *************************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'asterisk_recall' container] *****************************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the 'call_register' container] *******************************************************************************************************************************
changed: [127.0.0.1]

TASK [Creating the Systemd user folder] *************************************************************************************************************************************
changed: [127.0.0.1]

TASK [Download the Systemd Unit files] **************************************************************************************************************************************
changed: [127.0.0.1] => (item={'url': 'https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-asterisk_call.service', 'path': 'container-asterisk_call.service'})
changed: [127.0.0.1] => (item={'url': 'https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-asterisk_call_register.service', 'path': 'container-asterisk_call_register.service'})
changed: [127.0.0.1] => (item={'url': 'https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-asterisk_recall.service', 'path': 'container-asterisk_recall.service'})
changed: [127.0.0.1] => (item={'url': 'https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-asterisk_ws_monitor.service', 'path': 'container-asterisk_ws_monitor.service'})
changed: [127.0.0.1] => (item={'url': 'https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-caller_prometheus_webhook.service', 'path': 'container-caller_prometheus_webhook.service'})
changed: [127.0.0.1] => (item={'url': 'https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-caller_sms.service', 'path': 'container-caller_sms.service'})
changed: [127.0.0.1] => (item={'url': 'https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-generate_audio.service', 'path': 'container-generate_audio.service'})
changed: [127.0.0.1] => (item={'url': 'https://raw.githubusercontent.com/jcfdeb/py-phone-caller/main/assets/systemd-units/as-non-root-container/container-postgres_13.service', 'path': 'container-postgres_13.service'})

TASK [Enable and run the user SystemD services for 'py-phone-caller'] *******************************************************************************************************
changed: [127.0.0.1] => (item=container-asterisk_call.service)
changed: [127.0.0.1] => (item=container-asterisk_call_register.service)
changed: [127.0.0.1] => (item=container-asterisk_recall.service)
changed: [127.0.0.1] => (item=container-asterisk_ws_monitor.service)
changed: [127.0.0.1] => (item=container-caller_prometheus_webhook.service)
changed: [127.0.0.1] => (item=container-caller_sms.service)
changed: [127.0.0.1] => (item=container-generate_audio.service)
changed: [127.0.0.1] => (item=container-postgres_13.service)

TASK [Deleting the '/tmp' files] ********************************************************************************************************************************************
changed: [127.0.0.1] => (item=/tmp/db-schema.sql)
changed: [127.0.0.1] => (item=/tmp/caller_config.toml.jinja)

PLAY RECAP ******************************************************************************************************************************************************************
127.0.0.1                  : ok=23   changed=21   unreachable=0    failed=0    skipped=0    rescued=2    ignored=0   
```




* Firewalld rules to allow the needed connections 

```
[fedora@fedora-server ~]$ sudo firewall-cmd --add-source="192.168.122.0/24" --permanent
success

[fedora@fedora-server ~]$ sudo firewall-cmd --add-source="172.19.0.0/24" --permanent
success

[fedora@fedora-server ~]$ sudo firewall-cmd --add-port=8081/tcp --permanent
success

[fedora@fedora-server ~]$ sudo firewall-cmd --add-port=8082/tcp --permanent
success

[fedora@fedora-server ~]$ sudo firewall-cmd --add-port=8083/tcp --permanent
success

[fedora@fedora-server ~]$ sudo firewall-cmd --add-port=8084/tcp --permanent
success

[fedora@fedora-server ~]$ sudo firewall-cmd --reload
success
```


