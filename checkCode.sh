#!/bin/sh

dmypy run src tests
flake8 src tests
