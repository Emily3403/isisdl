#!/usr/bin/env python3


def application(env, start_response):
    start_response('200 OK', [('Content-Type', 'text/html')])
    response = "Hello"
    return [response.encode()]


