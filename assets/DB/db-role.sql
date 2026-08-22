-- PostgreSQL database and role creation for py_phone_caller.
-- Tables, schema, and migrations are automatically managed by Piccolo ORM via caller_register.
-- Please change the password with a strong password of your choice.

CREATE
DATABASE py_phone_caller;
CREATE ROLE py_phone_caller with LOGIN ENCRYPTED PASSWORD 'use-a-secure-password';
GRANT
ALL
PRIVILEGES
ON
DATABASE
py_phone_caller TO py_phone_caller;