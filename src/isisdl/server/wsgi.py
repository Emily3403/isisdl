#!/usr/bin/env python3
from typing import List, Any


def application(env: Any, start_response: Any) -> List[bytes]:
    print(env)
    raise ValueError
    start_response('200 OK', [('Content-Type', 'text/html')])
    response = "Hello"
    return [response.encode()]
