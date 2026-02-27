#!/usr/bin/env bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/ -v "$@"
