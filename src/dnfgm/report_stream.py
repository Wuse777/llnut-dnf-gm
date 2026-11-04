"""Bound report download lifetime and explicitly release its snapshot on disconnect."""
import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse


class ReportStream(StreamingResponse):
    """Own a synchronous generator, including while ASGI send is backpressured.

    An interrupted download must not contain a final complete marker. Shield
    cleanup from the response cancellation; never leave a snapshot/DB slot to GC.
    """
    timeout_seconds = 120

    def __init__(self, content, **kwargs):
        self.source = content
        super().__init__(content, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            with anyio.fail_after(self.timeout_seconds):
                await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(self.source.close)
