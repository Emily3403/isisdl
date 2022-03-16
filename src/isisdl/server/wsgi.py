#!/usr/bin/env python3
import json
from datetime import datetime
from typing import List, Any

working_dir =

def application(env: Any, start_response: Any) -> List[bytes]:
    try:
        length = int(env.get('CONTENT_LENGTH', '0'))
    except ValueError:
        length = 0

    body = env['wsgi.input'].read(length)

    try:
        dat = json.loads(str(body))
        with open("/home/isisdl-server/isisdl/src/isisdl/server/logs/v1/" + datetime.now().strftime("%y-%m-%d")) as f:
            f.write(json.dumps(dat, indent=4))

    except Exception:
        dat = None


    print(body)


    start_response('200 OK', [('Content-Type', 'text/html')])
    response = "Hello"
    return [response.encode()]
