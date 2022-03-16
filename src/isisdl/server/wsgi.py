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
    today = datetime.now().strftime("%y-%m-%d")

    try:
        data = json.loads(body.decode())

        subdir = "errors/" if "message" in data and data["message"].startswith("Assertion failed:") else "logs/"
        subpath = os.path.join("/home/isisdl-server/isisdl/src/isisdl/server/logs/v1", subdir, today)
        os.makedirs(subpath, exist_ok=True)

        with open(os.path.join(subpath, sha256(str(time.time()).encode()).hexdigest() + ".json"), "w") as f:
            # Validate that the data is json
            f.write(json.dumps(data, indent=4))

    except Exception:
        try:
            with open("/home/isisdl-server/isisdl/src/isisdl/server/logs/v1/snoops/" + today) as f:
                num = int(f.read())
        except Exception:
            num = 0

        with open("/home/isisdl-server/isisdl/src/isisdl/server/logs/v1/snoops/" + today, "w") as f:
            f.write(str(num + 1))

    start_response('200 OK', [('Content-Type', 'text/html')])
    return [b"Nothing to see here ..."]
