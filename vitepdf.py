#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VitePDF: right-click image and PDF tools for Windows.

This small file only starts the program. The parts live next to it:
  vp_core.py   the engine: pictures to PDF, compressing, size presets
  vp_ops.py    the other tools: merge, convert, pages, password, clean-up
  vp_ui.py     the windows
  vp_shell.py  right-click menus, installing and removing
  vp_main.py   reads the command and runs the right tool

Created by Atanu Sarkar. Made with Claude.
"""
import os
import sys

# Python runs in isolated mode (-I), which leaves this folder off the search
# path. Add it back: it is VitePDF's own folder, never the user's file folder.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vp_main import entry  # noqa: E402

if __name__ == "__main__":
    entry()
