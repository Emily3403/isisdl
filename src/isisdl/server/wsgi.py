#!/usr/bin/env python3
from typing import List, Any


def application(env: Any, start_response: Any) -> List[bytes]:
    print(env)

    try:
        length = int(env.get('CONTENT_LENGTH', '0'))
    except ValueError:
        length = 0

    body = env['wsgi.input'].read(length)

    print(body)


    start_response('200 OK', [('Content-Type', 'text/html')])
    response = "Hello"
    return [response.encode()]
