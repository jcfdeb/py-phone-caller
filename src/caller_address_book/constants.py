from py_phone_caller_utils.config import settings

CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT = (
    settings.caller_address_book.caller_address_book_route_add_contact
)
CALLER_ADDRESS_BOOK_ROUTE_MODIFY_CONTACT = (
    settings.caller_address_book.caller_address_book_route_modify_contact
)
CALLER_ADDRESS_BOOK_ROUTE_DELETE_CONTACT = (
    settings.caller_address_book.caller_address_book_route_delete_contact
)
CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT = (
    settings.caller_address_book.caller_address_book_route_on_call_contact
)
CALLER_ADDRESS_BOOK_PORT = int(settings.caller_address_book.caller_address_book_port)
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
