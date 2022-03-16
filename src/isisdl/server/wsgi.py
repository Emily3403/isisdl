#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime
from hashlib import sha256
from typing import List, Any

def application(env: Any, start_response: Any) -> List[bytes]:
    try:
        length = int(env.get('CONTENT_LENGTH', '0'))
    except ValueError:
        length = 0

    body: bytes = env['wsgi.input'].read(length)

    try:
        today = datetime.now().strftime("%y-%m-%d")
        os.makedirs("/home/isisdl-server/isisdl/src/isisdl/server/logs/v1/" + today, exist_ok=True)
        with open("/home/isisdl-server/isisdl/src/isisdl/server/logs/v1/" + today + "/" + sha256(str(time.time()).encode()).hexdigest(), "w") as f:
            # Validate that the data is json
            f.write(json.dumps(json.loads(body.decode()), indent=4))  # TODO: indent away

    except Exception as ex:
        pass


    start_response('200 OK', [('Content-Type', 'text/html')])
    return [b"Nothing to see here ..."]
