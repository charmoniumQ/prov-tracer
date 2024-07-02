
import typing
import json
import subprocess
from . import ops

OpTable = typing.Mapping[int, typing.Mapping[int, typing.Mapping[int, typing.List[ops.Op]]]]

def load_log(path: str) -> OpTable:
    ret: dict[int, dict[int, dict[int, list[ops.Op]]]] = {}


    lines = subprocess.run(
        ["probe", "dump", "--json", "--input", path], 
        capture_output=True, 
        encoding="utf-8"
    )
    jsonlines = [json.loads(x) for x in lines.stdout.strip().split('\n')]

    for item in jsonlines:
        pid: int = item['pid']
        epoch: int = item['exec_epoch']
        tid: int = item['tid']
        op: ops.Op = ops.Op(**item['op'])

        if not pid in ret:
            ret[pid] = {}
        if not epoch in ret[pid]:
            ret[pid][epoch] = {}
        if not tid in ret[pid][epoch]:
            ret[pid][epoch][tid] = []

        ret[pid][epoch][tid].append(op)

    return ret 
