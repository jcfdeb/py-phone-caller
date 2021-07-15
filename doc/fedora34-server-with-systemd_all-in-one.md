## Fedora 34 Server installation 

> Draft - Work In Progress

```bash
~# dnf install -y https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm
Last metadata expiration check: 0:02:14 ago on Thu 15 Jul 2021 09:25:22 PM CEST.
rpmfusion-free-release-34.noarch.rpm                                                                                                          18 kB/s |  11 kB     00:00    
rpmfusion-nonfree-release-34.noarch.rpm                                                                                                       16 kB/s |  11 kB     00:00    
Dependencies resolved.
=============================================================================================================================================================================
 Package                                               Architecture                       Version                             Repository                                Size
=============================================================================================================================================================================
Installing:
 rpmfusion-free-release                                noarch                             34-1                                @commandline                              11 k
 rpmfusion-nonfree-release                             noarch                             34-1                                @commandline                              11 k

Transaction Summary
=============================================================================================================================================================================
Install  2 Packages

Total size: 23 k
Installed size: 11 k
Downloading Packages:
Running transaction check
Transaction check succeeded.
Running transaction test
Transaction test succeeded.
Running transaction
  Preparing        :                                                                                                                                                     1/1 
  Installing       : rpmfusion-nonfree-release-34-1.noarch                                                                                                               1/2 
  Installing       : rpmfusion-free-release-34-1.noarch                                                                                                                  2/2 
  Verifying        : rpmfusion-free-release-34-1.noarch                                                                                                                  1/2 
  Verifying        : rpmfusion-nonfree-release-34-1.noarch                                                                                                               2/2 

Installed:
  rpmfusion-free-release-34-1.noarch                                                  rpmfusion-nonfree-release-34-1.noarch                                                 

Complete!
```

```bash
~# rpm --import "https://rpmfusion.org/keys?action=AttachFile&do=get&target=RPM-GPG-KEY-rpmfusion-nonfree-fedora-2020" 
```

```bash
~# dnf install -y postgresql-server asterisk asterisk-curl asterisk-pjsip asterisk-iax2 ffmpeg 
RPM Fusion for Fedora 34 - Free                                                                                                              557 kB/s | 941 kB     00:01    
RPM Fusion for Fedora 34 - Free - Updates                                                                                                    384 kB/s | 281 kB     00:00    
RPM Fusion for Fedora 34 - Nonfree                                                                                                           250 kB/s | 246 kB     00:00    
RPM Fusion for Fedora 34 - Nonfree - Updates                                                                                                  63 kB/s |  61 kB     00:00    
Dependencies resolved.
=============================================================================================================================================================================
 Package                                      Architecture              Version                                              Repository                                 Size
=============================================================================================================================================================================
Installing:
 asterisk                                     x86_64                    18.2.0-1.fc34.2                                      fedora                                    4.8 M
 ffmpeg                                       x86_64                    4.4-4.fc34                                           rpmfusion-free-updates                    1.6 M
 postgresql-server                            x86_64                    13.3-2.fc34                                          updates                                   5.8 M
Installing dependencies:
 SDL2                                         x86_64                    2.0.14-3.fc34                                        fedora                                    553 k
 alsa-lib                                     x86_64                    1.2.5.1-1.fc34                                       updates                                   484 k
 cairo                                        x86_64                    1.17.4-3.fc34                                        fedora                                    671 k
 cairo-gobject                                x86_64                    1.17.4-3.fc34                                        fedora                                     18 k
 ffmpeg-libs                                  x86_64                    4.4-4.fc34                                           rpmfusion-free-updates                    8.4 M
 flac-libs                                    x86_64                    1.3.3-7.fc34                                         fedora                                    220 k
 fontconfig                                   x86_64                    2.13.93-6.fc34                                       fedora                                    275 k
 freetype                                     x86_64                    2.10.4-3.fc34                                        fedora                                    394 k
 fribidi                                      x86_64                    1.0.10-4.fc34                                        fedora                                     86 k
 glibmm24                                     x86_64                    2.66.1-1.fc34                                        updates                                   674 k
 gmime                                        x86_64                    2.6.23-13.fc34                                       fedora                                    201 k
 gperftools-libs                              x86_64                    2.9.1-1.fc34                                         fedora                                    318 k
 graphite2                                    x86_64                    1.3.14-7.fc34                                        fedora                                     95 k
 gsm                                          x86_64                    1.0.19-5.fc34                                        updates                                    33 k
 harfbuzz                                     x86_64                    2.7.4-3.fc34                                         fedora                                    634 k
 ilbc                                         x86_64                    1.1.1-20.fc34                                        fedora                                     46 k
 intel-mediasdk                               x86_64                    21.1.3-1.fc34                                        fedora                                    2.6 M
 jack-audio-connection-kit                    x86_64                    1.9.17-1.fc34                                        updates                                   544 k
 jpegxl-libs                                  x86_64                    0.3.7-3.fc34                                         updates                                   932 k
 lame-libs                                    x86_64                    3.100-10.fc34                                        fedora                                    336 k
 libICE                                       x86_64                    1.0.10-6.fc34                                        fedora                                     71 k
 libSM                                        x86_64                    1.2.3-8.fc34                                         fedora                                     42 k
 libX11                                       x86_64                    1.7.0-3.fc34                                         fedora                                    661 k
 libX11-common                                noarch                    1.7.0-3.fc34                                         fedora                                    153 k
 libX11-xcb                                   x86_64                    1.7.0-3.fc34                                         fedora                                     12 k
 libXau                                       x86_64                    1.0.9-6.fc34                                         fedora                                     31 k
 libXext                                      x86_64                    1.3.4-6.fc34                                         fedora                                     39 k
 libXfixes                                    x86_64                    6.0.0-1.fc34                                         updates                                    19 k
 libXft                                       x86_64                    2.3.3-6.fc34                                         fedora                                     63 k
 libXi                                        x86_64                    1.7.10-6.fc34                                        fedora                                     39 k
 libXrender                                   x86_64                    0.9.10-14.fc34                                       fedora                                     27 k
 libXtst                                      x86_64                    1.2.3-14.fc34                                        fedora                                     20 k
 libXxf86vm                                   x86_64                    1.1.4-16.fc34                                        fedora                                     18 k
 libaom                                       x86_64                    3.1.1-1.fc34                                         updates                                   1.6 M
 libass                                       x86_64                    0.14.0-7.fc34                                        fedora                                    108 k
 libasyncns                                   x86_64                    0.8-20.fc34                                          fedora                                     30 k
 libavdevice                                  x86_64                    4.4-4.fc34                                           rpmfusion-free-updates                     75 k
 libbluray                                    x86_64                    1.3.0-1.fc34                                         updates                                   172 k
 libcdio                                      x86_64                    2.1.0-4.fc34                                         fedora                                    245 k
 libcdio-paranoia                             x86_64                    10.2+2.0.1-4.fc34                                    fedora                                     86 k
 libconfig                                    x86_64                    1.7.2-7.fc34                                         fedora                                     73 k
 libdatrie                                    x86_64                    0.2.13-1.fc34                                        fedora                                     32 k
 libdav1d                                     x86_64                    0.9.0-1.fc34                                         updates                                   431 k
 libdrm                                       x86_64                    2.4.107-1.fc34                                       updates                                   162 k
 libffado                                     x86_64                    2.4.4-3.fc34                                         fedora                                    858 k
 libglvnd                                     x86_64                    1:1.3.3-1.fc34                                       updates                                   137 k
 libglvnd-glx                                 x86_64                    1:1.3.3-1.fc34                                       updates                                   153 k
 libiec61883                                  x86_64                    1.2.0-26.fc34                                        fedora                                     41 k
 libmodplug                                   x86_64                    1:0.8.9.0-12.fc34                                    fedora                                    173 k
 libmysofa                                    x86_64                    1.2-4.fc34                                           fedora                                     42 k
 libogg                                       x86_64                    2:1.3.4-4.fc34                                       fedora                                     33 k
 libopenmpt                                   x86_64                    0.5.8-1.fc34                                         updates                                   569 k
 libpciaccess                                 x86_64                    0.16-4.fc34                                          fedora                                     27 k
 libpq                                        x86_64                    13.3-1.fc34                                          updates                                   202 k
 libraw1394                                   x86_64                    2.1.2-13.fc34                                        fedora                                     65 k
 librsvg2                                     x86_64                    2.50.6-1.fc34                                        updates                                   3.4 M
 libsamplerate                                x86_64                    0.1.9-8.fc34                                         fedora                                    1.4 M
 libsigc++20                                  x86_64                    2.10.7-1.fc34                                        updates                                    38 k
 libsndfile                                   x86_64                    1.0.31-3.fc34                                        fedora                                    210 k
 libsrtp                                      x86_64                    2.3.0-6.fc34                                         updates                                    58 k
 libthai                                      x86_64                    0.1.28-6.fc34                                        fedora                                    213 k
 libtheora                                    x86_64                    1:1.1.1-29.fc34                                      fedora                                    163 k
 libudfread                                   x86_64                    1.1.2-1.fc34                                         updates                                    33 k
 libunwind                                    x86_64                    1.4.0-5.fc34                                         fedora                                     65 k
 libv4l                                       x86_64                    1.20.0-3.fc34                                        fedora                                    199 k
 libva                                        x86_64                    2.11.0-1.fc34                                        fedora                                    102 k
 libvdpau                                     x86_64                    1.4-4.fc34                                           fedora                                     17 k
 libvmaf                                      x86_64                    2.1.1-1.fc34                                         updates                                   171 k
 libvorbis                                    x86_64                    1:1.3.7-3.fc34                                       fedora                                    199 k
 libvpx                                       x86_64                    1.9.0-3.fc34                                         fedora                                    1.0 M
 libwayland-client                            x86_64                    1.19.0-1.fc34                                        fedora                                     32 k
 libxcb                                       x86_64                    1.13.1-7.fc34                                        fedora                                    230 k
 libxml++                                     x86_64                    2.42.1-1.fc34                                        updates                                   100 k
 libxshmfence                                 x86_64                    1.3-8.fc34                                           fedora                                     12 k
 lilv                                         x86_64                    0.24.10-2.fc34                                       fedora                                     81 k
 llvm-libs                                    x86_64                    12.0.0-2.fc34                                        updates                                    23 M
 lv2                                          x86_64                    1.18.0-2.fc34                                        fedora                                     94 k
 mesa-filesystem                              x86_64                    21.1.4-1.fc34                                        updates                                    17 k
 mesa-libGL                                   x86_64                    21.1.4-1.fc34                                        updates                                   171 k
 mesa-libglapi                                x86_64                    21.1.4-1.fc34                                        updates                                    55 k
 mesa-vulkan-drivers                          x86_64                    21.1.4-1.fc34                                        updates                                   4.8 M
 mpg123-libs                                  x86_64                    1.26.2-3.fc34                                        fedora                                    314 k
 ocl-icd                                      x86_64                    2.3.0-1.fc34                                         updates                                    66 k
 openal-soft                                  x86_64                    1.19.1-12.fc34                                       fedora                                    544 k
 opencore-amr                                 x86_64                    0.1.5-12.fc34                                        rpmfusion-free                            176 k
 openjpeg2                                    x86_64                    2.4.0-3.fc34                                         updates                                   163 k
 opus                                         x86_64                    1.3.1-8.fc34                                         fedora                                    202 k
 pango                                        x86_64                    1.48.7-1.fc34                                        updates                                   299 k
 postgresql                                   x86_64                    13.3-2.fc34                                          updates                                   1.5 M
 pulseaudio-libs                              x86_64                    14.2-3.fc34                                          fedora                                    728 k
 rav1e-libs                                   x86_64                    0.4.1-2.fc34                                         updates                                   774 k
 serd                                         x86_64                    0.30.10-2.fc34                                       fedora                                     62 k
 sord                                         x86_64                    0.16.6-2.fc34                                        fedora                                     45 k
 soxr                                         x86_64                    0.1.3-9.fc34                                         fedora                                     84 k
 speex                                        x86_64                    1.2.0-8.fc34                                         fedora                                     68 k
 speexdsp                                     x86_64                    1.2.0-3.fc34                                         fedora                                    453 k
 spirv-tools-libs                             x86_64                    2020.5-5.20201208.gitb27b1af.fc34                    fedora                                    1.2 M
 sratom                                       x86_64                    0.6.6-2.fc34                                         fedora                                     25 k
 srt-libs                                     x86_64                    1.4.2-4.fc34                                         fedora                                    277 k
 svt-av1-libs                                 x86_64                    0.8.6-4.fc34                                         fedora                                    4.6 M
 vapoursynth-libs                             x86_64                    51-2.fc34                                            fedora                                    446 k
 vid.stab                                     x86_64                    1.1.0-16.20190213gitaeabc8d.fc34                     fedora                                     49 k
 vo-amrwbenc                                  x86_64                    0.1.3-14.fc34                                        rpmfusion-free                             78 k
 vulkan-loader                                x86_64                    1.2.162.0-2.fc34                                     fedora                                    126 k
 x264-libs                                    x86_64                    0.161-6.20210412git55d517b.fc34                      rpmfusion-free                            686 k
 x265-libs                                    x86_64                    3.5-1.fc34                                           rpmfusion-free                            1.3 M
 xml-common                                   noarch                    0.6.3-56.fc34                                        fedora                                     31 k
 xvidcore                                     x86_64                    1.3.7-5.fc34                                         rpmfusion-free                            255 k
 zimg                                         x86_64                    3.0.1-3.fc34                                         fedora                                    289 k
 zvbi                                         x86_64                    0.2.35-13.fc34                                       fedora                                    421 k
Installing weak dependencies:
 jxl-pixbuf-loader                            x86_64                    0.3.7-3.fc34                                         updates                                   414 k

Transaction Summary
=============================================================================================================================================================================
Install  114 Packages

Total download size: 87 M
Installed size: 321 M
Downloading Packages:
[...]
```

**Note**: for voices in other languages than english, for example if you want the italian audio recordings  install 
the 'asterisk-sounds-core-it-wav' package. 


```bash
~# /usr/bin/postgresql-setup --initdb
 * Initializing database in '/var/lib/pgsql/data'
 * Initialized, logs are in /var/lib/pgsql/initdb_postgresql.log
```

```bash
~# systemctl enable --now postgresql
```

```bash
~# systemctl status postgresql
● postgresql.service - PostgreSQL database server
     Loaded: loaded (/usr/lib/systemd/system/postgresql.service; enabled; vendor preset: disabled)
     Active: active (running) since Thu 2021-07-15 21:40:20 CEST; 6s ago
    Process: 3840 ExecStartPre=/usr/libexec/postgresql-check-db-dir postgresql (code=exited, status=0/SUCCESS)
   Main PID: 3842 (postmaster)
      Tasks: 8 (limit: 2325)
     Memory: 16.0M
        CPU: 82ms
     CGroup: /system.slice/postgresql.service
             ├─3842 /usr/bin/postmaster -D /var/lib/pgsql/data
             ├─3843 postgres: logger
             ├─3845 postgres: checkpointer
             ├─3846 postgres: background writer
             ├─3847 postgres: walwriter
             ├─3848 postgres: autovacuum launcher
             ├─3849 postgres: stats collector
             └─3850 postgres: logical replication launcher

Jul 15 21:40:19 fedora systemd[1]: Starting PostgreSQL database server...
Jul 15 21:40:20 fedora postmaster[3842]: 2021-07-15 21:40:20.086 CEST [3842] LOG:  redirecting log output to logging collector process
Jul 15 21:40:20 fedora postmaster[3842]: 2021-07-15 21:40:20.086 CEST [3842] HINT:  Future log output will appear in directory "log".
Jul 15 21:40:20 fedora systemd[1]: Started PostgreSQL database server.
```


```bash
~# systemctl enable --now asterisk
Created symlink /etc/systemd/system/multi-user.target.wants/asterisk.service → /usr/lib/systemd/system/asterisk.service.
```


```bash
~# systemctl status asterisk
● asterisk.service - Asterisk PBX and telephony daemon.
     Loaded: loaded (/usr/lib/systemd/system/asterisk.service; enabled; vendor preset: disabled)
     Active: active (running) since Thu 2021-07-15 21:56:02 CEST; 2s ago
   Main PID: 4960 (asterisk)
      Tasks: 41 (limit: 2325)
     Memory: 22.9M
        CPU: 774ms
     CGroup: /system.slice/asterisk.service
             └─4960 /usr/sbin/asterisk -f -C /etc/asterisk/asterisk.conf

Jul 15 21:56:04 fedora asterisk[4960]: [Jul 15 21:56:04] WARNING[4960]: res_phoneprov.c:1232 get_defaults: Unable to find a valid server address or name.
Jul 15 21:56:04 fedora asterisk[4960]: [Jul 15 21:56:04] NOTICE[4960]: res_smdi.c:1424 load_module: No SMDI interfaces are available to listen on, not starting SMDI listene>
Jul 15 21:56:04 fedora asterisk[4960]: [Jul 15 21:56:04] ERROR[4960]: ari/config.c:312 process_config: No configured users for ARI
Jul 15 21:56:04 fedora asterisk[4960]: [Jul 15 21:56:04] NOTICE[4960]: confbridge/conf_config_parser.c:2370 verify_default_profiles: Adding default_menu menu to app_confbri>
Jul 15 21:56:04 fedora asterisk[4960]: [Jul 15 21:56:04] NOTICE[4960]: cel_custom.c:95 load_config: No mappings found in cel_custom.conf. Not logging CEL to custom CSVs.
Jul 15 21:56:04 fedora asterisk[4960]: [Jul 15 21:56:04] WARNING[4960]: loader.c:2381 load_modules: Some non-required modules failed to load.
Jul 15 21:56:04 fedora asterisk[4960]: [Jul 15 21:56:04] ERROR[4960]: loader.c:2396 load_modules: Error loading module 'res_ari_mailboxes.so': /usr/lib64/asterisk/modules/r>
Jul 15 21:56:04 fedora asterisk[4960]: [Jul 15 21:56:04] ERROR[4960]: loader.c:2396 load_modules: Error loading module 'res_prometheus.so': /usr/lib64/asterisk/modules/res_>
Jul 15 21:56:04 fedora asterisk[4960]: [Jul 15 21:56:04] ERROR[4960]: loader.c:2396 load_modules: cdr_syslog declined to load.
```

```bash
~# dnf install -y git
Last metadata expiration check: 0:27:51 ago on Thu 15 Jul 2021 09:31:36 PM CEST.
Dependencies resolved.
=============================================================================================================================================================================
 Package                                           Architecture                      Version                                        Repository                          Size
=============================================================================================================================================================================
Installing:
 git                                               x86_64                            2.31.1-3.fc34                                  updates                            121 k
Installing dependencies:
 git-core                                          x86_64                            2.31.1-3.fc34                                  updates                            3.6 M
 git-core-doc                                      noarch                            2.31.1-3.fc34                                  updates                            2.3 M
 perl-AutoLoader                                   noarch                            5.74-477.fc34                                  updates                             31 k
 perl-B                                            x86_64                            1.80-477.fc34                                  updates                            189 k
 perl-Carp                                         noarch                            1.50-458.fc34                                  fedora                              29 k
 perl-Class-Struct                                 noarch                            0.66-477.fc34                                  updates                             32 k
 perl-Data-Dumper                                  x86_64                            2.174-460.fc34                                 fedora                              56 k
 perl-Digest                                       noarch                            1.19-2.fc34                                    fedora                              26 k
 perl-Digest-MD5                                   x86_64                            2.58-2.fc34                                    fedora                              36 k
 perl-DynaLoader                                   x86_64                            1.47-477.fc34                                  updates                             36 k
 perl-Encode                                       x86_64                            4:3.08-459.fc34                                fedora                             1.7 M
 perl-Errno                                        x86_64                            1.30-477.fc34                                  updates                             25 k
 perl-Error                                        noarch                            1:0.17029-5.fc34                               fedora                              42 k
 perl-Exporter                                     noarch                            5.74-459.fc34                                  fedora                              32 k
 perl-Fcntl                                        x86_64                            1.13-477.fc34                                  updates                             31 k
 perl-File-Basename                                noarch                            2.85-477.fc34                                  updates                             27 k
 perl-File-Find                                    noarch                            1.37-477.fc34                                  updates                             36 k
 perl-File-Path                                    noarch                            2.18-2.fc34                                    fedora                              36 k
 perl-File-Temp                                    noarch                            1:0.231.100-2.fc34                             fedora                              60 k
 perl-File-stat                                    noarch                            1.09-477.fc34                                  updates                             27 k
 perl-FileHandle                                   noarch                            2.03-477.fc34                                  updates                             26 k
 perl-Getopt-Long                                  noarch                            1:2.52-2.fc34                                  fedora                              61 k
 perl-Getopt-Std                                   noarch                            1.12-477.fc34                                  updates                             26 k
 perl-Git                                          noarch                            2.31.1-3.fc34                                  updates                             44 k
 perl-HTTP-Tiny                                    noarch                            0.076-458.fc34                                 fedora                              55 k
 perl-IO                                           x86_64                            1.43-477.fc34                                  updates                             97 k
 perl-IPC-Open3                                    noarch                            1.21-477.fc34                                  updates                             33 k
 perl-MIME-Base64                                  x86_64                            3.16-2.fc34                                    fedora                              30 k
 perl-Net-SSLeay                                   x86_64                            1.90-2.fc34                                    fedora                             357 k
 perl-POSIX                                        x86_64                            1.94-477.fc34                                  updates                            107 k
 perl-PathTools                                    x86_64                            3.78-459.fc34                                  fedora                              86 k
 perl-Pod-Escapes                                  noarch                            1:1.07-458.fc34                                fedora                              20 k
 perl-Pod-Perldoc                                  noarch                            3.28.01-459.fc34                               fedora                              85 k
 perl-Pod-Simple                                   noarch                            1:3.42-2.fc34                                  fedora                             216 k
 perl-Pod-Usage                                    noarch                            4:2.01-2.fc34                                  fedora                              41 k
 perl-Scalar-List-Utils                            x86_64                            4:1.56-459.fc34                                fedora                              72 k
 perl-SelectSaver                                  noarch                            1.02-477.fc34                                  updates                             22 k
 perl-Socket                                       x86_64                            4:2.032-1.fc34                                 updates                             54 k
 perl-Storable                                     x86_64                            1:3.21-458.fc34                                fedora                              97 k
 perl-Symbol                                       noarch                            1.08-477.fc34                                  updates                             24 k
 perl-Term-ANSIColor                               noarch                            5.01-459.fc34                                  fedora                              49 k
 perl-Term-Cap                                     noarch                            1.17-458.fc34                                  fedora                              22 k
 perl-TermReadKey                                  x86_64                            2.38-9.fc34                                    fedora                              36 k
 perl-Text-ParseWords                              noarch                            3.30-458.fc34                                  fedora                              16 k
 perl-Text-Tabs+Wrap                               noarch                            2013.0523-458.fc34                             fedora                              23 k
 perl-Time-Local                                   noarch                            2:1.300-5.fc34                                 fedora                              34 k
 perl-URI                                          noarch                            5.09-1.fc34                                    fedora                             109 k
 perl-base                                         noarch                            2.27-477.fc34                                  updates                             26 k
 perl-constant                                     noarch                            1.33-459.fc34                                  fedora                              23 k
 perl-if                                           noarch                            0.60.800-477.fc34                              updates                             24 k
 perl-interpreter                                  x86_64                            4:5.32.1-477.fc34                              updates                             81 k
 perl-lib                                          x86_64                            0.65-477.fc34                                  updates                             25 k
 perl-libnet                                       noarch                            3.13-2.fc34                                    fedora                             127 k
 perl-libs                                         x86_64                            4:5.32.1-477.fc34                              updates                            2.0 M
 perl-mro                                          x86_64                            1.23-477.fc34                                  updates                             38 k
 perl-overload                                     noarch                            1.31-477.fc34                                  updates                             56 k
 perl-overloading                                  noarch                            0.02-477.fc34                                  updates                             23 k
 perl-parent                                       noarch                            1:0.238-458.fc34                               fedora                              14 k
 perl-podlators                                    noarch                            1:4.14-458.fc34                                fedora                             113 k
 perl-subs                                         noarch                            1.03-477.fc34                                  updates                             22 k
 perl-vars                                         noarch                            1.05-477.fc34                                  updates                             23 k
Installing weak dependencies:
 perl-IO-Socket-IP                                 noarch                            0.41-3.fc34                                    fedora                              43 k
 perl-IO-Socket-SSL                                noarch                            2.070-2.fc34                                   fedora                             214 k
 perl-Mozilla-CA                                   noarch                            20200520-4.fc34                                fedora                              12 k
 perl-NDBM_File                                    x86_64                            1.15-477.fc34                                  updates                             32 k

Transaction Summary
=============================================================================================================================================================================
Install  66 Packages

Total download size: 13 M
Installed size: 57 M
Downloading Packages:
```

```bash
~# asterisk  -rx "core show version"
Asterisk 18.2.0 built by mockbuild @ buildhw-x86-04.iad2.fedoraproject.org on a x86_64 running Linux on 2021-02-08 08:28:42 UTC
```


> Asterisk configuration here

```bash
[root@fedora ~]# cd /opt/
```

```bash
[root@fedora opt]# git clone https://github.com/jcfdeb/py-phone-caller.git
Cloning into 'py-phone-caller'...
remote: Enumerating objects: 66, done.
remote: Counting objects: 100% (66/66), done.
remote: Compressing objects: 100% (46/46), done.
remote: Total 66 (delta 18), reused 57 (delta 15), pack-reused 0
Receiving objects: 100% (66/66), 216.82 KiB | 1.69 MiB/s, done.
Resolving deltas: 100% (18/18), done.
```


```bash
[root@fedora opt]# chown -R daemon.daemon py-phone-caller
```


```bash
[root@fedora opt]# chmod 750 py-phone-caller
```

```bash
[root@fedora opt]# ls -al
total 4
drwxr-xr-x.  3 root   root     29 Jul 15 22:10 .
dr-xr-xr-x. 17 root   root    224 Jun 28 17:51 ..
drwxr-x---.  7 daemon daemon 4096 Jul 15 22:10 py-phone-caller
```

```bash
[root@fedora py-phone-caller]# ls
assets                  caller_prometheus_webhook.py  doc                             Dockerfile.caller_prometheus_webhook  generate_audio.py  requirements.in
asterisk_call.py        caller_sms.py                 Dockerfile.asterisk_call        Dockerfile.caller_sms                 LICENSE            requirements.txt
asterisk_recall.py      call_register.py              Dockerfile.asterisk_recall      Dockerfile.call_register              local_utils
asterisk_ws_monitor.py  config                        Dockerfile.asterisk_ws_monitor  Dockerfile.generate_audio             README.md
```

```bash
[root@fedora py-phone-caller]# rm -rf Dockerfile.* requirements.in 
```

```bash
[root@fedora py-phone-caller]# ls
assets            asterisk_recall.py      caller_prometheus_webhook.py  call_register.py  doc                LICENSE      README.md
asterisk_call.py  asterisk_ws_monitor.py  caller_sms.py                 config            generate_audio.py  local_utils  requirements.txt
```

```bash
[root@fedora py-phone-caller]# python3.9 -m venv venv 
```

```bash
[root@fedora py-phone-caller]# source venv/bin/activate
```

```bash
(venv) [root@fedora py-phone-caller]# pip3.9 install -r requirements.txt 
Collecting aiodns==3.0.0
  Downloading aiodns-3.0.0-py3-none-any.whl (5.0 kB)
Collecting aiohttp==3.7.4.post0
  Downloading aiohttp-3.7.4.post0-cp39-cp39-manylinux2014_x86_64.whl (1.4 MB)
     |████████████████████████████████| 1.4 MB 2.2 MB/s 
Collecting aiologger==0.6.1
  Downloading aiologger-0.6.1.tar.gz (20 kB)
Collecting anyio==3.2.1
  Downloading anyio-3.2.1-py3-none-any.whl (75 kB)
     |████████████████████████████████| 75 kB 389 kB/s 
Collecting async-timeout==3.0.1
  Downloading async_timeout-3.0.1-py3-none-any.whl (8.2 kB)
Collecting asyncpg==0.23.0
  Downloading asyncpg-0.23.0-cp39-cp39-manylinux_2_5_x86_64.manylinux1_x86_64.whl (2.8 MB)
     |████████████████████████████████| 2.8 MB 358 kB/s 
Collecting attrs==21.2.0
  Downloading attrs-21.2.0-py2.py3-none-any.whl (53 kB)
     |████████████████████████████████| 53 kB 262 kB/s 
Collecting certifi==2021.5.30
  Downloading certifi-2021.5.30-py2.py3-none-any.whl (145 kB)
     |████████████████████████████████| 145 kB 3.3 MB/s 
Collecting cffi==1.14.5
  Downloading cffi-1.14.5-cp39-cp39-manylinux1_x86_64.whl (406 kB)
     |████████████████████████████████| 406 kB 3.7 MB/s 
Collecting chardet==4.0.0
  Downloading chardet-4.0.0-py2.py3-none-any.whl (178 kB)
     |████████████████████████████████| 178 kB 3.6 MB/s 
Collecting click==8.0.1
[...]
WARNING: You are using pip version 21.0.1; however, version 21.1.3 is available.
You should consider upgrading via the '/opt/py-phone-caller/venv/bin/python3.9 -m pip install --upgrade pip' command.
```

```bash
(venv) [root@fedora py-phone-caller]# pip3.9 install --upgrade pip
Requirement already satisfied: pip in ./venv/lib/python3.9/site-packages (21.0.1)
Collecting pip
  Downloading pip-21.1.3-py3-none-any.whl (1.5 MB)
     |████████████████████████████████| 1.5 MB 1.7 MB/s 
Installing collected packages: pip
  Attempting uninstall: pip
    Found existing installation: pip 21.0.1
    Uninstalling pip-21.0.1:
      Successfully uninstalled pip-21.0.1
Successfully installed pip-21.1.3
```

```bash
(venv) [root@fedora py-phone-caller]# chown -R daemon.daemon /opt/py-phone-caller
```

```bash
(venv) [root@fedora py-phone-caller]# ls -al
total 84
drwxr-x---. 8 daemon daemon  4096 Jul 15 22:16 .
drwxr-xr-x. 3 root   root      29 Jul 15 22:10 ..
drwxr-xr-x. 6 daemon daemon    93 Jul 15 22:10 assets
-rw-r--r--. 1 daemon daemon  9011 Jul 15 22:10 asterisk_call.py
-rw-r--r--. 1 daemon daemon  4759 Jul 15 22:10 asterisk_recall.py
-rw-r--r--. 1 daemon daemon  9470 Jul 15 22:10 asterisk_ws_monitor.py
-rw-r--r--. 1 daemon daemon  6996 Jul 15 22:10 caller_prometheus_webhook.py
-rw-r--r--. 1 daemon daemon  2904 Jul 15 22:10 caller_sms.py
-rw-r--r--. 1 daemon daemon 14558 Jul 15 22:10 call_register.py
drwxr-xr-x. 2 daemon daemon    32 Jul 15 22:10 config
drwxr-xr-x. 2 daemon daemon    56 Jul 15 22:10 doc
-rw-r--r--. 1 daemon daemon  3286 Jul 15 22:10 generate_audio.py
drwxr-xr-x. 8 daemon daemon   163 Jul 15 22:10 .git
-rw-r--r--. 1 daemon daemon  1813 Jul 15 22:10 .gitignore
-rw-r--r--. 1 daemon daemon  1076 Jul 15 22:10 LICENSE
drwxr-xr-x. 3 daemon daemon    89 Jul 15 22:10 local_utils
-rw-r--r--. 1 daemon daemon  2314 Jul 15 22:10 README.md
-rw-r--r--. 1 daemon daemon  1533 Jul 15 22:10 requirements.txt
drwxr-xr-x. 5 daemon daemon    74 Jul 15 22:16 venv
```

```bash
(venv) [root@fedora py-phone-caller]# cd assets/

```bash
(venv) [root@fedora assets]# ls -al
total 4
drwxr-xr-x. 6 daemon daemon   93 Jul 15 22:10 .
drwxr-x---. 8 daemon daemon 4096 Jul 15 22:16 ..
drwxr-xr-x. 2 daemon daemon   46 Jul 15 22:10 DB
drwxr-xr-x. 2 daemon daemon   52 Jul 15 22:10 docker-compose
drwxr-xr-x. 2 daemon daemon  140 Jul 15 22:10 generic-audio-for-dialplan
drwxr-xr-x. 2 daemon daemon  227 Jul 15 22:10 systemd-units
```

```bash
(venv) [root@fedora assets]# cd systemd-units/
```

```bash
(venv) [root@fedora systemd-units]# ls
asterisk-call.service    asterisk-ws-monitor.service        caller_sms.service     generate-audio.service
asterisk-recall.service  caller_prometheus_webhook.service  call-register.service
```

```bash
(venv) [root@fedora systemd-units]# cat call-register.service 
[Unit]
Description=Python Asterisk Caller - Call Register
Before=asterisk-ws-monitor.service
After=network.target

[Service]
Environment=CALLER_CONFIG="/opt/py-phone-caller/config/caller_config.toml"
Type=simple
User=daemon
Group=daemon
WorkingDirectory=/opt/py-phone-caller/
ExecStart=/bin/bash -c 'source venv/bin/activate && python call_register.py'
StandardOutput=journal
Restart=always
RestartSec=15s
TimeoutStopSec=5
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
(venv) [root@fedora systemd-units]# cp *.service /etc/systemd/system
```


```bash
(venv) [root@fedora systemd-units]# ls -al /etc/systemd/system
total 36
drwxr-xr-x. 22 root root 4096 Jul 15 22:24 .
drwxr-xr-x.  5 root root  280 Jun 28 17:52 ..
-rw-r--r--.  1 root root  523 Jul 15 22:24 asterisk-call.service
-rw-r--r--.  1 root root  552 Jul 15 22:24 asterisk-recall.service
-rw-r--r--.  1 root root  562 Jul 15 22:24 asterisk-ws-monitor.service
drwxr-xr-x.  2 root root   35 Jun 28 17:52 basic.target.wants
drwxr-xr-x.  2 root root   31 Jun 28 17:53 bluetooth.target.wants
-rw-r--r--.  1 root root  594 Jul 15 22:24 caller_prometheus_webhook.service
-rw-r--r--.  1 root root  526 Jul 15 22:24 caller_sms.service
-rw-r--r--.  1 root root  530 Jul 15 22:24 call-register.service
lrwxrwxrwx.  1 root root   37 Jun 28 17:52 ctrl-alt-del.target -> /usr/lib/systemd/system/reboot.target
lrwxrwxrwx.  1 root root   41 Jun 28 17:53 dbus-org.bluez.service -> /usr/lib/systemd/system/bluetooth.service
lrwxrwxrwx.  1 root root   41 Jun 28 17:53 dbus-org.fedoraproject.FirewallD1.service -> /usr/lib/systemd/system/firewalld.service
lrwxrwxrwx.  1 root root   45 Jun 28 17:52 dbus-org.freedesktop.home1.service -> /usr/lib/systemd/system/systemd-homed.service
lrwxrwxrwx.  1 root root   44 Jun 28 17:53 dbus-org.freedesktop.ModemManager1.service -> /usr/lib/systemd/system/ModemManager.service
lrwxrwxrwx.  1 root root   57 Jun 28 17:53 dbus-org.freedesktop.nm-dispatcher.service -> /usr/lib/systemd/system/NetworkManager-dispatcher.service
lrwxrwxrwx.  1 root root   44 Jun 28 17:52 dbus-org.freedesktop.oom1.service -> /usr/lib/systemd/system/systemd-oomd.service
lrwxrwxrwx.  1 root root   48 Jun 28 17:52 dbus-org.freedesktop.resolve1.service -> /usr/lib/systemd/system/systemd-resolved.service
lrwxrwxrwx.  1 root root   43 Jun 28 17:52 dbus.service -> /usr/lib/systemd/system/dbus-broker.service
lrwxrwxrwx.  1 root root   41 Jun 28 17:56 default.target -> /usr/lib/systemd/system/multi-user.target
drwxr-xr-x.  2 root root   29 Jul 10 11:08 dnf-automatic-install.service.d
drwxr-xr-x.  2 root root   23 Jul 10 11:08 dnf-automatic-install.timer.d
-rw-r--r--.  1 root root  525 Jul 15 22:24 generate-audio.service
drwxr-xr-x.  2 root root   32 Jun 28 17:52 getty.target.wants
drwxr-xr-x.  2 root root   29 Jun 28 17:53 graphical.target.wants
drwxr-xr-x.  2 root root 4096 Jul 15 21:42 multi-user.target.wants
drwxr-xr-x.  2 root root   48 Jun 28 17:53 network-online.target.wants
drwxr-xr-x.  2 root root   33 Jun 28 17:53 nfs-blkmap.service.requires
drwxr-xr-x.  2 root root   33 Jun 28 17:53 nfs-idmapd.service.requires
drwxr-xr-x.  2 root root   33 Jun 28 17:53 nfs-mountd.service.requires
drwxr-xr-x.  2 root root   33 Jun 28 17:53 nfs-server.service.requires
drwxr-xr-x.  2 root root   52 Jun 28 17:53 remote-fs.target.wants
drwxr-xr-x.  2 root root   33 Jun 28 17:53 rpc-gssd.service.requires
drwxr-xr-x.  2 root root   33 Jun 28 17:53 rpc-statd-notify.service.requires
drwxr-xr-x.  2 root root   33 Jun 28 17:53 rpc-statd.service.requires
drwxr-xr-x.  2 root root  212 Jun 28 17:53 sockets.target.wants
drwxr-xr-x.  2 root root  184 Jun 28 17:53 sysinit.target.wants
drwxr-xr-x.  2 root root   44 Jun 28 17:52 systemd-homed.service.wants
drwxr-xr-x.  2 root root  193 Jul 10 11:08 timers.target.wants
```

```bash
(venv) [root@fedora DB]# pwd
/opt/py-phone-caller/assets/DB
```

```bash
(venv) [root@fedora DB]# ls
db-role.sql  db-schema.sql
```

```bash
(venv) [root@fedora DB]# cat db-role.sql 
-- This file should by used before 'db-schema.sql'
-- Please change the password with another of your choice (it should be strong).
-- Later the password is needed in the 'caller_config.toml' file

CREATE DATABASE py_phone_caller;
CREATE ROLE py_phone_caller with LOGIN ENCRYPTED PASSWORD '.-7=9|W_8YzIC*p[/9)D"d6!s*{.DD0W1Mi2*^';
GRANT ALL PRIVILEGES ON DATABASE py_phone_caller TO py_phone_caller;
```

```bash
(venv) [root@fedora DB]# cp *.sql /tmp/
```

```bash
(venv) [root@fedora DB]# chown postgres. /tmp/*.sql
```

```bash
(venv) [root@fedora DB]# su - postgres
```

```bash
[postgres@fedora ~]$ psql -f /tmp/db-role.sql 
CREATE DATABASE
CREATE ROLE
GRANT
```

```bash
[postgres@fedora ~]$ psql -f /tmp/db-schema.sql -d py_phone_caller
SET
SET
SET
SET
SET
CREATE EXTENSION
COMMENT
SET
SET
SET
CREATE TABLE
ALTER TABLE
CREATE SEQUENCE
ALTER TABLE
ALTER SEQUENCE
CREATE TABLE
ALTER TABLE
CREATE SEQUENCE
ALTER TABLE
ALTER SEQUENCE
ALTER TABLE
ALTER TABLE
ALTER TABLE
ALTER TABLE
REVOKE
REVOKE
GRANT
GRANT
```


* File: /var/lib/pgsql/data/pg_hba.conf

```bash
[...]
# "local" is for Unix domain socket connections only
local   all             all                                     peer
# IPv4 local connections:
host    all             all             127.0.0.1/32            ident
host    py_phone_caller py_phone_caller 192.168.122.105/24      md5  
# IPv6 local connections:
[...]
```

* File: /var/lib/pgsql/data/postgresql.conf

```bash
[...]
listen_addresses = 'localhost,192.168.122.105'
#listen_addresses = 'localhost'         # what IP address(es) to listen on;
[...]
```


```bash
(venv) [root@fedora DB]# systemctl restart postgresql
```


```bash
(venv) [root@fedora DB]# psql -h 192.168.122.105 -U py_phone_caller -d py_phone_caller
Password for user py_phone_caller: 
psql (13.3)
Type "help" for help.

py_phone_caller=> \dt
                   List of relations
 Schema |        Name        | Type  |      Owner      
--------+--------------------+-------+-----------------
 public | asterisk_ws_events | table | py_phone_caller
 public | calls              | table | py_phone_caller
(2 rows)

py_phone_caller=> select * from calls;
 id | phone | message | asterisk_chan | msg_chk_sum | call_chk_sum | unique_chk_sum | times_to_dial | dialed_times | seconds_to_forget | first_dial | last_dial | heard_at | 
acknowledge_at | cycle_done 
----+-------+---------+---------------+-------------+--------------+----------------+---------------+--------------+-------------------+------------+-----------+----------+-
---------------+------------
(0 rows)

py_phone_caller=> 
```