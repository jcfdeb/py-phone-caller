# Work in Progress - Draft


[root@fedora ~]# dnf install -y ansible


[root@fedora podman]ansible-galaxy collection install community.postgresqlql
Process install dependency map
Starting collection install process
Installing 'community.postgresql:1.4.0' to '/root/.ansible/collections/ansible_collections/community/postgresql'

[root@fedora ~]# ansible-galaxy collection install containers.podman
Process install dependency map
Starting collection install process
Installing 'containers.podman:1.6.1' to '/root/.ansible/collections/ansible_collections/containers/podman'

[root@fedora podman]# dnf install -y python3-psycopg2
Last metadata expiration check: 1:45:10 ago on Thu 22 Jul 2021 03:58:44 PM CEST.
Dependencies resolved.
=============================================================================================================================================================================
 Package                                        Architecture                         Version                                      Repository                            Size
=============================================================================================================================================================================
Installing:
 python3-psycopg2                               x86_64                               2.8.6-3.fc34                                 fedora                               183 k

Transaction Summary
=============================================================================================================================================================================
Install  1 Package

Total download size: 183 k
Installed size: 605 k
Downloading Packages:
python3-psycopg2-2.8.6-3.fc34.x86_64.rpm                                                                                                     593 kB/s | 183 kB     00:00    
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Total                                                                                                                                        199 kB/s | 183 kB     00:00     
Running transaction check
Transaction check succeeded.
Running transaction test
Transaction test succeeded.
Running transaction
  Preparing        :                                                                                                                                                     1/1 
  Installing       : python3-psycopg2-2.8.6-3.fc34.x86_64                                                                                                                1/1 
  Running scriptlet: python3-psycopg2-2.8.6-3.fc34.x86_64                                                                                                                1/1 
  Verifying        : python3-psycopg2-2.8.6-3.fc34.x86_64                                                                                                                1/1 

Installed:
  python3-psycopg2-2.8.6-3.fc34.x86_64                                                                                                                                       

Complete!








