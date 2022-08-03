import pytest
from base64 import b64encode
from aiohttp import web, ClientSession
from aiohttp_basicauth_middleware import basic_auth_middleware

from src.caller_utils import caller_configuration as conf

from src.asterisk_caller.asterisk_caller import gen_headers
from src.asterisk_caller.asterisk_caller import send_ari_continue

ASTERISK_CALL_PORT = int(conf.get_asterisk_call_port())
ASTERISK_USER = conf.get_asterisk_user()
ASTERISK_PASS = conf.get_asterisk_pass()
ASTERISK_ARI_CHANNELS = conf.get_asterisk_ari_channels()
ASTERISK_CHAN = "1646889318"


@pytest.mark.asyncio
async def test_gen_headers():
    actual = await gen_headers("abc")
    expected = {'Authorization': 'Basic YWJj'}
    assert actual == expected


@pytest.mark.asyncio
async def handler_send_ari_continue(request):
    return web.Response(body=b"body text", status=204)


async def test_send_ari_continue(aiohttp_server):
    # Server Part with HTTP Basic Authentication
    app = web.Application()
    app.router.add_route("POST", f"/{ASTERISK_ARI_CHANNELS}/{ASTERISK_CHAN}/continue", handler_send_ari_continue)
    app.middlewares.append(basic_auth_middleware(('/',), {ASTERISK_USER: ASTERISK_PASS}, ))
    await aiohttp_server(app, port=ASTERISK_CALL_PORT)

    # Client Part
    url = f"http://127.0.0.1:{ASTERISK_CALL_PORT}/{ASTERISK_ARI_CHANNELS}/{ASTERISK_CHAN}/continue"
    session = ClientSession()
    auth_string = f"{ASTERISK_USER}:{ASTERISK_PASS}"
    headers = {"Authorization": f"Basic {str(b64encode(bytearray(auth_string, 'utf8')), 'utf-8')}"}

    response = await send_ari_continue(headers, ASTERISK_ARI_CHANNELS, url)
    await session.close()
    assert response == 204

