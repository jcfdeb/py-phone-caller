# Caller Address Book

HTTP service for managing contacts and on-call rotations used by the call and
recall flows.

## Responsibilities
- Add, modify, and delete contacts.
- Fetch the active on-call contact.
- Import and export contacts in CSV format.
- Initialize and migrate the database schema (Piccolo ORM).

## HTTP API
Routes are configured in `settings.toml` under `[caller_address_book]`:
- POST `/<caller_address_book_route_add_contact>`
- PUT `/<caller_address_book_route_modify_contact>/{id}`
- DELETE `/<caller_address_book_route_delete_contact>`
- GET `/<caller_address_book_route_on_call_contact>`
- GET `/contacts_export_csv`
- POST `/contacts_import_csv`

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m caller_address_book.caller_address_book
```

## Docker
```bash
docker build -t caller-address-book -f src/caller_address_book/Dockerfile src/
```
