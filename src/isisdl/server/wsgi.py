#!/usr/bin/env python3
from typing import List, Any
import cgitb

cgitb.enable()


def application(_: Any, start_response: Any) -> List[bytes]:
    start_response('200 OK', [('Content-Type', 'text/html')])
    response = "Hello"
    raise ValueError
    return [response.encode()]
