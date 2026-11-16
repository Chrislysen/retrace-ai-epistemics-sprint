"""Console-free launch with the existing venv and a memory-only credential pipe.

Run this helper using the BASE interpreter, not the venv redirector. No job
breakaway, ignored signals, automatic retries or automatic restart is used.
The scientific driver still verifies its freeze, STOP and admission deadline.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(r'C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1112-611-0_26.1112.611.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe')
VENV = ROOT / '.venv-v6c' / 'Scripts' / 'python.exe'
FREEZE = ROOT / 'data/frontier-v6n-freeze.json'
PROBE = ROOT / 'results/frontier-v6n-recovery/console-probe-v2.json'
IO_PROOF = ROOT / 'results/frontier-v6n-recovery/console-io-proof-v2.txt'


def require(value, message):
    if not value:
        raise ValueError(message)


def environment():
    require(os.name == 'nt' and RUNTIME.is_file() and VENV.is_file(), 'Exact Windows interpreter paths required')
    # The CPython 3.12 venv redirector sets this same nonsecret variable before
    # starting the base interpreter. Direct launch avoids its secondary job.
    env = os.environ.copy()
    env['__PYVENV_LAUNCHER__'] = str(VENV)
    return env


def write_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def probe():
    require(not PROBE.exists() and not IO_PROOF.exists(), 'Preserve prior launch probe')
    code = (
        "import sys,json,ctypes,importlib.metadata,ssl; "
        "detached=bool(ctypes.windll.kernel32.FreeConsole()); "
        "marker=sys.stdin.readline().strip(); "
        "f=open(sys.argv[1],'xb'); f.write(b'offline-file-proof\\n'); f.flush(); f.close(); "
        "from scripts.host_guard_v6n import console_state; "
        "buf=ctypes.create_unicode_buffer(32768); "
        "ctypes.windll.kernel32.GetModuleFileNameW(None,buf,len(buf)); "
        "import aiohttp; "
        "print(json.dumps({'console':console_state(),'free_console_succeeded':detached,"
        "'stdin_pipe_verified':marker=='offline-pipe-proof','stdout_pipe_verified':True,"
        "'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
        "'reported_executable':sys.executable,'actual_executable':buf.value,"
        "'python':sys.version,'aiohttp':importlib.metadata.version('aiohttp'),"
        "'aiohttp_file':aiohttp.__file__,'ssl_default_context_created':bool(ssl.create_default_context())}))"
    )
    completed = subprocess.run([str(RUNTIME), '-X', 'utf8', '-B', '-c', code, str(IO_PROOF)], cwd=ROOT,
        env=environment(), input='offline-pipe-proof\n', capture_output=True, text=True,
        encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    write_new(PROBE.parent / ('console-probe-attempt-' + uuid.uuid4().hex + '.json'), {
        'schema': 'retrace.frontier-v6n-console-probe-attempt.v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'provider_calls': 0,
        'returncode': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr,
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    require(completed.returncode == 0, 'Offline console probe failed: ' + completed.stderr)
    observed = json.loads(completed.stdout)
    require(observed['free_console_succeeded'] is True and observed['stdin_pipe_verified'] is True
            and observed['stdout_pipe_verified'] is True, 'Post-detachment pipe operation failed')
    require(observed['console']['console_free_verified'] is True, 'Actual child console remains attached')
    require(Path(observed['actual_executable']).resolve() == RUNTIME.resolve(), 'Unexpected actual interpreter')
    require(Path(observed['prefix']).resolve() == (ROOT / '.venv-v6c').resolve(), 'Venv discovery changed')
    require(Path(observed['aiohttp_file']).resolve().is_relative_to((ROOT / '.venv-v6c').resolve())
            and observed['aiohttp'] == '3.14.5', 'Installed inference dependency changed')
    require(IO_PROOF.read_bytes() == b'offline-file-proof\n', 'Post-detachment file write failed')
    result = {'schema': 'retrace.frontier-v6n-console-probe.v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'passed': True, 'provider_calls': 0,
        'network_used': False, 'creationflags': subprocess.CREATE_NO_WINDOW,
        'detached_process': False, 'job_breakaway': False, 'signal_handlers_changed': False,
        'credential_used': False, 'observed': observed, 'post_detachment_file_write_verified': True,
        'io_proof_path': IO_PROOF.relative_to(ROOT).as_posix(),
        'io_proof_sha256': hashlib.sha256(IO_PROOF.read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_new(PROBE, result)
    return result


def execute(expected):
    require(hashlib.sha256(FREEZE.read_bytes()).hexdigest() == expected, 'Exact n freeze required')
    require(json.loads(PROBE.read_text(encoding='utf-8'))['passed'] is True, 'Offline console probe required')
    require(datetime.now(timezone.utc) < datetime(2026, 11, 16, 6, 56, tzinfo=timezone.utc), 'Admission cutoff reached')
    base = ROOT / 'results/frontier-v6n'
    for name in ('continuation', 'budget', 'STOP', 'runner-console.log', 'launch-receipt.json'):
        require(not (base / name).exists(), 'Nonfresh n destination: ' + name)
    key = sys.stdin.readline().strip()
    require(len(key) >= 8 and not any(c.isspace() for c in key), 'Valid stdin credential required')
    base.mkdir(parents=True, exist_ok=True)
    with (base / 'runner-console.log').open('xb') as log:
        bootstrap = ("import ctypes,runpy,sys\n"
            "if not ctypes.windll.kernel32.FreeConsole():\n    raise RuntimeError('Console detach failed')\n"
            "sys.argv=['scripts/run_frontier_v6n.py','--execute-sha256',sys.argv[1]]\n"
            "runpy.run_path('scripts/run_frontier_v6n.py',run_name='__main__')")
        child = subprocess.Popen([str(RUNTIME), '-X', 'utf8', '-B', '-c', bootstrap, expected],
            cwd=ROOT, env=environment(), stdin=subprocess.PIPE,
            stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        child.stdin.write((key + '\n').encode('utf-8'))
        child.stdin.close()
        key = None
        receipt = {'schema': 'retrace.frontier-v6n-launch.v1', 'created_at': datetime.now(timezone.utc).isoformat(),
            'launcher_pid': os.getpid(), 'worker_pid': child.pid, 'freeze_sha256': expected,
            'actual_executable': str(RUNTIME), 'venv_launcher_convention': str(VENV),
            'creationflags': subprocess.CREATE_NO_WINDOW, 'detached_process': False,
            'job_breakaway': False, 'signal_handlers_changed': False,
            'free_console_before_driver': True, 'credential_channel': 'memory-only stdin',
            'admission_deadline_utc': '2026-11-16T06:56:00+00:00',
            'user_hard_cutoff_utc': '2026-11-16T07:00:00+00:00',
            'note': 'Actual worker verifies console state again before any provider request. Launch is not evidence of a request.'}
        write_new(base / 'launch-receipt.json', receipt)
        print(json.dumps(receipt), flush=True)
        return child.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--probe', action='store_true')
    action.add_argument('--execute-sha256')
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe(), ensure_ascii=False))
    else:
        sys.exit(execute(args.execute_sha256))
