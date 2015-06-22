#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demo StackHut service
"""
import sh  # allows shelling out to user code
from app import SERVICES
import json

def gen_error(code, msg=''):
    return dict(error=code, msg=msg)

def run(req):
    iface_name, func_name = req['method'].split('.')
    params = req['params']

    if iface_name in SERVICES:
        iface_impl = SERVICES[iface_name]
        try:
            func = getattr(iface_impl, func_name)
        except AttributeError:
            return gen_error(-32601)
        # if hasattr(iface_impl, "barrister_pre"):
        #     pre_hook = getattr(iface_impl, "barrister_pre")
        #     pre_hook(context, params)
        if params:
            result = func(*params)
        else:
            result = func()
        return dict(result=result)
    else:
        return gen_error(-32601)

if __name__ == "__main__":
    # open the input
    with open("./service_req.json", "r") as f:
        req = json.loads(f.read())

    # run the command
    try:
        resp = run(req)
    except Exception as e:
        resp = gen_error(-32000, str(e))

    # save the output
    with open("./service_resp.json", "w") as f:
        f.write(json.dumps(resp))

    exit(0)
