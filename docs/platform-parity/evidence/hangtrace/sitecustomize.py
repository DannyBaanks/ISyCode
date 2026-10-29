"""Temporary Python stack capture for one Windows pytest hang investigation."""
import faulthandler
import sys

faulthandler.enable(file=sys.__stderr__)
faulthandler.dump_traceback_later(12, repeat=True, file=sys.__stderr__)
