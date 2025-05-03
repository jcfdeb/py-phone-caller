from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import \
    AsteriskWsEvents


async def insert_ws_event(asterisk_chan, event_type, json_data):
    """
    Inserts a new event record into the Asterisk WebSocket events table.

    This asynchronous function ensures the table exists and inserts the provided channel, event type, and JSON data.

    Args:
        asterisk_chan (str): The identifier of the Asterisk channel.
        event_type (str): The type of the event.
        json_data (str): The JSON-encoded event data.

    Returns:
        None
    """
    await AsteriskWsEvents.create_table(if_not_exists=True)
    await AsteriskWsEvents.insert(
        AsteriskWsEvents(
            asterisk_chan=asterisk_chan, event_type=event_type, json_data=json_data
        )
    )


async def select_ws_events():
    """
    Retrieves all event records from the Asterisk WebSocket events table.

    This asynchronous function ensures the table exists and returns all stored event records.

    Returns:
        list: A list of all Asterisk WebSocket event records.
    """
    await AsteriskWsEvents.create_table(if_not_exists=True)
    return await AsteriskWsEvents.select()
