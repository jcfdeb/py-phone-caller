from twilio.rest import Client


def sms_twilio(
    sms_body, sms_to, twilio_account_sid, twilio_auth_token, twilio_sms_from
):
    """
    Sends an SMS message using the Twilio API.

    This function creates a Twilio client, sends the SMS with the provided credentials and message details, and returns the message status.

    Args:
        sms_body (str): The content of the SMS message.
        sms_to (str): The recipient's phone number.
        twilio_account_sid (str): The Twilio account SID.
        twilio_auth_token (str): The Twilio authentication token.
        twilio_sms_from (str): The sender's phone number (Twilio number).

    Returns:
        str: The status of the sent message (e.g., 'queued').
    """
    client = Client(twilio_account_sid, twilio_auth_token)

    message = client.messages.create(body=sms_body, from_=twilio_sms_from, to=sms_to)
    return message.status  # -> 'queued'
