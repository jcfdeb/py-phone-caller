from asterisk_ws_events_table import AsteriskWsEvents


async def insert_ws_event(asterisk_chan, event_type, json_data):
    """Insert to the database the events received from the Asterisk ARI"""
    await AsteriskWsEvents.create_table(if_not_exists=True)
    await AsteriskWsEvents.insert(
        AsteriskWsEvents(
            asterisk_chan=asterisk_chan, event_type=event_type, json_data=json_data
        )
    )


async def select_ws_events():
    """Selects the rows of the Asterisk WebSocket events table"""
    return await AsteriskWsEvents.select()
