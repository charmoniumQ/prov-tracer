from typer.testing import CliRunner
import tarfile
from .cli import app
from . import parse_probe_log
from . import analysis
import pathlib
import typing
import networkx as nx

runner = CliRunner()

def test_diff_cmd():
    result = runner.invoke(app,["record","--make","diff","../flake.nix","../flake.lock"])
    input: pathlib.Path = pathlib.Path("probe_log")
    assert input.exists()
    probe_log_tar_obj = tarfile.open(input, "r")
    process_tree_prov_log = parse_probe_log.parse_probe_log_tar(probe_log_tar_obj)
    probe_log_tar_obj.close()
    process_graph = analysis.provlog_to_digraph(process_tree_prov_log)
    paths = ['../flake.nix','../flake.lock']
    file_descriptors = []
    reserved_file_descriptors = [0, 1, 2]

    dfs_edges = list(nx.dfs_edges(process_graph))
      
    for edge in dfs_edges:
        curr_pid = edge[0][0]
        curr_epoch_idx = edge[0][1]
        curr_tid = edge[0][2]
        curr_op_idx = edge[0][3]
        curr_node_op = get_op_from_provlog(process_tree_prov_log, curr_pid, curr_epoch_idx, curr_tid, curr_op_idx)
        if(isinstance(curr_node_op,parse_probe_log.OpenOp)):
            file_descriptors.append(curr_node_op.fd)
            path = curr_node_op.path.path
            if path in paths:
                paths.remove(path)
        elif(isinstance(curr_node_op,parse_probe_log.CloseOp)):
            fd = curr_node_op.low_fd
            if fd in reserved_file_descriptors:
                continue
            assert fd in file_descriptors
            file_descriptors.remove(fd)
    
    assert len(file_descriptors) == 0
    assert len(paths) == 0
    

def test_bash_in_bash():
    result = runner.invoke(app,["record", "bash", "-c", "head ../flake.nix ; head ../flake.lock"])

    assert result.exit_code == 0
    input: pathlib.Path = pathlib.Path("probe_log")
    assert input.exists()
    probe_log_tar_obj = tarfile.open(input, "r")
    process_tree_prov_log = parse_probe_log.parse_probe_log_tar(probe_log_tar_obj)
    probe_log_tar_obj.close()
    process_graph = analysis.provlog_to_digraph(process_tree_prov_log)

    paths = ['../flake.nix', '../flake.lock']
    # to ensure files which are opened are closed
    file_descriptors = []
    # to ensure WaitOp ret is same as the child process pid
    check_wait = []
    # to ensure the child process has ExecOp, OpenOp and CloseOp
    check_child_processes = []
    # to ensure child process touch the right file
    process_file_map = {}
    # to ensure right number of child processes are created
    current_child_process = 0
    reserved_file_descriptors = [0, 1, 2]
    dfs_edges = list(nx.dfs_edges(process_graph))
    
    parent_process_id = dfs_edges[0][0][0]
    process_file_map[paths[len(paths)-1]] = parent_process_id
    for edge in dfs_edges:
        curr_op_idx = edge[0][3]
        curr_epoch_idx = edge[0][1]
        curr_pid = edge[0][0]
        curr_tid = edge[0][2]
        curr_node_op =   get_op_from_provlog(process_tree_prov_log, curr_pid, curr_epoch_idx, curr_tid, curr_op_idx)
        if(isinstance(curr_node_op,parse_probe_log.OpenOp)):
            file_descriptors.append(curr_node_op.fd)
            path = curr_node_op.path.path
            if path in paths:
                # ensure the right cloned process has OpenOp for the path
                assert curr_pid == process_file_map[path]
                if curr_pid!=parent_process_id:
                    assert curr_pid in check_child_processes
                    check_child_processes.remove(curr_pid)
        elif(isinstance(curr_node_op,parse_probe_log.CloseOp)):
            fd = curr_node_op.low_fd
            if fd in reserved_file_descriptors:
                continue
            assert fd in file_descriptors
            file_descriptors.remove(fd)
        elif(isinstance(curr_node_op,parse_probe_log.CloneOp)):
            next_op = get_op_from_provlog(process_tree_prov_log, edge[1][0], edge[1][1], edge[1][2], edge[1][3])
            if isinstance(next_op,parse_probe_log.ExecOp):
                assert edge[1][0] == curr_node_op.child_process_id
                check_child_processes.append(curr_node_op.child_process_id)
                continue
            current_child_process+=1
            check_wait.append(curr_node_op.child_process_id)
            process_file_map[paths[current_child_process-1]] = curr_node_op.child_process_id
        elif(isinstance(curr_node_op,parse_probe_log.WaitOp)):
            ret_pid = curr_node_op.ret
            wait_option = curr_node_op.options
            if wait_option == 0:
                assert ret_pid in check_wait
                check_wait.remove(ret_pid)
            
            

    # number of clone operations is number of commands-1
    assert current_child_process == len(paths)-1
    assert len(file_descriptors) == 0
    assert len(check_wait) == 0
    assert len(process_file_map.items()) == len(paths)
    assert len(check_child_processes) == 0 
        
def test_command_not_found():
    result = runner.invoke(app,["record", "cmd"])
    assert result.exit_code == 0
    assert "Error: Command not found." in result.output

def test_empty_path():
    result = runner.invoke(app,["record"])
    assert result.exit_code == 2
    assert "Error: Missing argument 'CMD...'." in result.output

def get_op_from_provlog(process_tree_prov_log,pid,exec_epoch_id,tid,op_idx):
    return process_tree_prov_log.processes[pid].exec_epochs[exec_epoch_id].threads[tid].ops[op_idx].data