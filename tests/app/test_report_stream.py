"""ASGI lifecycle evidence, without real sockets or production data."""
import asyncio
import pytest
from starlette.requests import ClientDisconnect
from dnfgm.report_stream import ReportStream


@pytest.mark.parametrize('mode',['disconnect','slow','complete','receive_disconnect'])
def test_download_explicitly_closes_owned_generator(mode):
    state={'open':False,'closed':False};bodies=[]
    def generate():
        state['open']=True
        try:
            yield 'metadata\n'
            yield 'complete\n'
        finally:
            state['open']=False;state['closed']=True
    async def run():
        body_started=asyncio.Event()
        async def receive():
            await body_started.wait()
            if mode=='receive_disconnect':return {'type':'http.disconnect'}
            await asyncio.sleep(10)
        async def send(message):
            if message['type']=='http.response.body':
                body_started.set()
                if mode=='disconnect':raise OSError('synthetic client disconnect')
                if mode in ('slow','receive_disconnect'):await asyncio.sleep(10)
                bodies.append(message['body'])
        response=ReportStream(generate());response.timeout_seconds=.1
        scope={'type':'http','asgi':{'spec_version':'2.0' if mode=='receive_disconnect' else '2.4'}}
        if mode=='disconnect':
            with pytest.raises(ClientDisconnect):await response(scope,receive,send)
        elif mode=='slow':
            with pytest.raises(TimeoutError):await response(scope,receive,send)
        else:await response(scope,receive,send)
    asyncio.run(run())
    assert state=={'open':False,'closed':True}
    assert (b'complete\n' in bodies)==(mode=='complete')
