from twilio.rest import Client


def sms_twilio(
    sms_body, sms_to, twilio_account_sid, twilio_auth_token, twilio_sms_from
):
    client = Client(twilio_account_sid, twilio_auth_token)

    message = client.messages.create(body=sms_body, from_=twilio_sms_from, to=sms_to)
    return message.status  # -> 'queued'
