"""Recording pass-through in front of the ledger: logs every request and response as JSON lines.

Test equipment only. It changes nothing; the agent's key travels through and is not written to the log.
"""
import json
import os
import time
import httpx
from fastapi import FastAPI, Request, Response

UPSTREAM = os.environ['UPSTREAM']
LOG = os.environ['REQUEST_LOG']
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def parse(raw):
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode(errors='replace')


@app.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
async def forward(path: str, request: Request):
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() in ('x-agent-key', 'content-type')}
    started = time.time()
    async with httpx.AsyncClient(timeout=60) as client:
        upstream = await client.request(request.method, f'{UPSTREAM}/{path}', params=request.query_params,
                                        content=body, headers=headers)
    with open(LOG, 'a') as log:
        log.write(json.dumps({
            't': round(started, 3), 'method': request.method, 'path': '/' + path,
            'query': dict(request.query_params), 'key_sent': 'x-agent-key' in request.headers,
            'request': parse(body) if body else None, 'status': upstream.status_code,
            'response': parse(upstream.content), 'seconds': round(time.time() - started, 3)}) + '\n')
    return Response(upstream.content, upstream.status_code, media_type=upstream.headers.get('content-type'))
