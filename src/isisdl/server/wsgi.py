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

        data = json.loads(body.decode())

        if "message" in data and data["message"].startswith("Assertion failed:"):
            subdir = "errors/"
        else:
            subdir = "logs/"


        with open(os.path.join("/home/isisdl-server/isisdl/src/isisdl/server/logs/v1", subdir, today, sha256(str(time.time()).encode()).hexdigest() + ".json"), "w") as f:
            # Validate that the data is json
            f.write(json.dumps(data, indent=4))

    except Exception:
        pass


    start_response('200 OK', [('Content-Type', 'text/html')])
    return [b"Nothing to see here ..."]
