### Kubernetes Deployment - draft

After applying the '03_postgresql_13.yml' manifest, some operations inside the POD are needed. 

  * The role and DB creation
  * Restore of the DB schema 

> For the SQL files please check the '**assets/DB**' folder

* Get the complete POD name
```bash
[fedora@fedora k8s]$ kubectl -n py-phone-caller get pods | grep postgresql
NAME                                     READY   STATUS    RESTARTS   AGE
postgresql-deployment-6d98db6844-8fnrb   1/1     Running   0          63s
```

* Open a shell inside the POD
> If you can't install '**nano**' you can also use '**vi**', yet installed inside the container image.
```bash
[fedora@fedora k8s]$ kubectl -n py-phone-caller exec -it postgresql-deployment-6d98db6844-8fnrb -- bash

bash-5.1# apk add nano
fetch https://dl-cdn.alpinelinux.org/alpine/v3.14/main/x86_64/APKINDEX.tar.gz
fetch https://dl-cdn.alpinelinux.org/alpine/v3.14/community/x86_64/APKINDEX.tar.gz
(1/2) Installing libmagic (5.40-r1)
(2/2) Installing nano (5.7-r2)
Executing busybox-1.33.1-r3.trigger
OK: 146 MiB in 35 packages
bash-5.1# su - postgres
```

* Crete the role and the DB
```bash
postgresql-deployment-6d98db6844-8fnrb:~$ nano /tmp/db-role.sql
-- This file should by used before 'db-schema.sql'
-- Please change the password with another of your choice (it should be strong).
-- Later this password is requiered in the 'caller_config.toml' file

CREATE DATABASE py_phone_caller;
CREATE ROLE py_phone_caller with LOGIN ENCRYPTED PASSWORD 'use-a-secure-password';
GRANT ALL PRIVILEGES ON DATABASE py_phone_caller TO py_phone_caller;
```

```bash
postgresql-deployment-6d98db6844-8fnrb:~$ psql -f /tmp/db-role.sql
CREATE DATABASE
CREATE ROLE
GRANT
```

* Import the DB schema
```bash
postgresql-deployment-6d98db6844-8fnrb:~$ nano /tmp/db-schema.sql
--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;

--
-- Name: plpgsql; Type: EXTENSION; Schema: -; Owner:
--

CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION plpgsql; Type: COMMENT; Schema: -; Owner:
--

COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';


SET search_path = public, pg_catalog;

SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: asterisk_ws_events; Type: TABLE; Schema: public; Owner: py_phone_caller; Tablespace:
--

CREATE TABLE asterisk_ws_events (
    id integer NOT NULL,
    asterisk_chan character varying(64),
    event_type character varying(64),
    json_data json
);


ALTER TABLE public.asterisk_ws_events OWNER TO py_phone_caller;

--
-- Name: asterisk_ws_events_id_seq; Type: SEQUENCE; Schema: public; Owner: py_phone_caller
--

CREATE SEQUENCE asterisk_ws_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.asterisk_ws_events_id_seq OWNER TO py_phone_caller;

--
-- Name: asterisk_ws_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: py_phone_caller
--

ALTER SEQUENCE asterisk_ws_events_id_seq OWNED BY asterisk_ws_events.id;


--
-- Name: calls; Type: TABLE; Schema: public; Owner: py_phone_caller; Tablespace:
--

CREATE TABLE calls (
    id integer NOT NULL,
    phone character varying(64),
    message character varying(1024),
    asterisk_chan character varying(64),
    msg_chk_sum character varying(64),
    call_chk_sum character varying(64),
    unique_chk_sum character varying(64),
    times_to_dial smallint,
    dialed_times smallint,
    seconds_to_forget integer,
    first_dial timestamp without time zone,
    last_dial timestamp without time zone,
    heard_at timestamp without time zone,
    acknowledge_at timestamp without time zone,
    cycle_done boolean DEFAULT false
);


ALTER TABLE public.calls OWNER TO py_phone_caller;

--
-- Name: calls_id_seq; Type: SEQUENCE; Schema: public; Owner: py_phone_caller
--

CREATE SEQUENCE calls_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.calls_id_seq OWNER TO py_phone_caller;

--
-- Name: calls_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: py_phone_caller
--

ALTER SEQUENCE calls_id_seq OWNED BY calls.id;


--
-- Name: id; Type: DEFAULT; Schema: public; Owner: py_phone_caller
--

ALTER TABLE ONLY asterisk_ws_events ALTER COLUMN id SET DEFAULT nextval('asterisk_ws_events_id_seq'::regclass);


--
-- Name: id; Type: DEFAULT; Schema: public; Owner: py_phone_caller
--

ALTER TABLE ONLY calls ALTER COLUMN id SET DEFAULT nextval('calls_id_seq'::regclass);


--
-- Name: asterisk_ws_events_pkey; Type: CONSTRAINT; Schema: public; Owner: py_phone_caller; Tablespace:
--

ALTER TABLE ONLY asterisk_ws_events
    ADD CONSTRAINT asterisk_ws_events_pkey PRIMARY KEY (id);


--
-- Name: calls_pkey; Type: CONSTRAINT; Schema: public; Owner: py_phone_caller; Tablespace:
--

ALTER TABLE ONLY calls
    ADD CONSTRAINT calls_pkey PRIMARY KEY (id);


--
-- Name: public; Type: ACL; Schema: -; Owner: py_phone_caller
--

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM py_phone_caller;
GRANT ALL ON SCHEMA public TO py_phone_caller;
GRANT ALL ON SCHEMA public TO PUBLIC;


--
-- PostgreSQL database dump complete
--
```

```bash
postgresql-deployment-6d98db6844-8fnrb:~$ psql -f /tmp/db-schema.sql -d py_phone_caller
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