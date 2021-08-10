-- This file should by used before 'db-schema.sql'
-- Please change the password with another of your choice (it should be strong).
-- Later this password is required in the 'caller_config.toml' file

CREATE DATABASE py_phone_caller;
CREATE ROLE py_phone_caller with LOGIN ENCRYPTED PASSWORD 'use-a-secure-password';
GRANT ALL PRIVILEGES ON DATABASE py_phone_caller TO py_phone_caller;