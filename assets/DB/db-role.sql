-- This file should by used before 'db-schema.sql'
-- Please change the password with another of your choice (it should be strong).
-- Later the password is needed in the 'caller_config.toml' file

CREATE DATABASE py_phone_caller;
CREATE ROLE py_phone_caller with LOGIN ENCRYPTED PASSWORD '.-7=9|W_8YzIC*p[/9)D"d6!s*{.DD0W1Mi2*^';
GRANT ALL PRIVILEGES ON DATABASE py_phone_caller TO py_phone_caller;