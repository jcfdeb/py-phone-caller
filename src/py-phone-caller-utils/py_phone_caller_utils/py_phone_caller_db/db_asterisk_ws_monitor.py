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
    
    await AsteriskWsEvents.insert(
        AsteriskWsEvents(
            asterisk_chan=asterisk_chan, event_type=event_type, json_data=json_data
        )
    )


def insert_ws_event_sync(asterisk_chan, event_type, json_data):
    """
    Insert a WebSocket event into the database synchronously.

    This function creates the `AsteriskWsEvents` table if it does not exist and
    inserts a new WebSocket event record into the table. The inserted data includes
    the asterisk channel, event type, and JSON data representing the event details.

    :param asterisk_chan: The identifier of the asterisk channel associated with
                          the event.
    :type asterisk_chan: str
    :param event_type: The type of the event being inserted.
    :type event_type: str
    :param json_data: JSON-formatted data containing event-specific information.
    :type json_data: dict
    :return: None
    """
    
    AsteriskWsEvents.insert(
        AsteriskWsEvents(
            asterisk_chan=asterisk_chan, event_type=event_type, json_data=json_data
        )
    ).run_sync()


async def select_ws_events():
    """
    Selects WebSocket events from the database and ensures the table is created if it does not
    already exist. This asynchronous function first ensures that the table `AsteriskWsEvents`
    is present in the database by creating it if necessary. Then it retrieves all records from
    the table.

    :return: A list of selected WebSocket events from the `AsteriskWsEvents` table.
    :rtype: list
    """
    
    return await AsteriskWsEvents.select()


def select_ws_events_sync():
    """
    Selects all events from the Asterisk WebSocket events table in a synchronous manner.

    This function ensures the table for Asterisk WebSocket events exists by creating it
    if it does not, and then selects all records from the corresponding table.

    :return: A list of all selected records from the Asterisk WebSocket events table.
    :rtype: list
    """
    
    return AsteriskWsEvents.select().run_sync()
