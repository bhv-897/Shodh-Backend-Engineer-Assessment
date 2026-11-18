"""Small Docker-backed runner for untrusted Python contest submissions."""
from __future__ import annotations

import io
import tarfile
import threading
import time
from dataclasses import dataclass
from uuid import uuid4

import docker
from docker.errors import ImageNotFound

OUTPUT_LIMIT = 64 * 1024
IMAGE = "python:3.12-slim"


@dataclass
class CaseResult:
    verdict: str
    stdout: str = ""
    stderr: str = ""
    execution_time_ms: int = 0


class DockerPythonRunner:
    def __init__(self, client=None, timeout_seconds=2.0, attempt_id=None, lease_token=None):
        self.client = client or docker.from_env()
        self.timeout_seconds = timeout_seconds
        self.attempt_id = attempt_id
        self.lease_token = lease_token

    def _lease_labels(self):
        labels = {"app": "easecoding-judge"}
        if self.attempt_id is not None:
            labels["judge_attempt_id"] = str(self.attempt_id)
        if self.lease_token is not None:
            labels["judge_lease_token"] = str(self.lease_token)
        return labels

    def cleanup_lease(self, attempt_id: int, lease_token: str):
        filters = {"label": ["app=easecoding-judge", f"judge_attempt_id={attempt_id}", f"judge_lease_token={lease_token}"]}
        for container in self.client.containers.list(all=True, filters=filters):
            try:
                container.kill()
            except docker.errors.NotFound:
                pass
            try:
                container.remove(force=True)
            except docker.errors.NotFound:
                pass
        volume_filters = {"label": ["app=easecoding-judge-case", f"judge_attempt_id={attempt_id}", f"judge_lease_token={lease_token}"]}
        for volume in self.client.volumes.list(filters=volume_filters):
            try:
                volume.remove(force=True)
            except docker.errors.NotFound:
                pass

    def _ensure_image(self):
        try:
            self.client.images.get(IMAGE)
        except ImageNotFound:
            self.client.images.pull(IMAGE)

    def run_case(self, source_code: str, input_data: str, timeout_seconds: float | None = None) -> CaseResult:
        self._ensure_image()
        labels = self._lease_labels()
        volume_labels = {**labels, "app": "easecoding-judge-case"}
        volume = self.client.volumes.create(name=f"easecoding-judge-{uuid4().hex}", labels=volume_labels)
        stager = None
        container = None
        output = bytearray()
        diagnostics = bytearray()
        output_lock = threading.Lock()
        log_errors = []
        timed_out = False
        overflow = threading.Event()
        started = None
        compile_failure_marker = f"EASECODING_COMPILE_FAILURE_{uuid4().hex}"
        compile_and_run = (
            "import sys, traceback\n"
            "path = '/submission/main.py'\n"
            f"marker = {compile_failure_marker!r}\n"
            "try:\n"
            "    with open(path, encoding='utf-8') as source_file:\n"
            "        source = source_file.read()\n"
            "    code = compile(source, path, 'exec')\n"
            "except (SyntaxError, ValueError, UnicodeError):\n"
            "    sys.stderr.write(marker + '\\n')\n"
            "    traceback.print_exc()\n"
            "    raise SystemExit(86)\n"
            "sys.stdin = open('/submission/input.txt', encoding='utf-8')\n"
            "sys.argv = [path]\n"
            "exec(code, {'__name__': '__main__', '__file__': path})\n"
        )
        try:
            # Use a one-off writable staging container, then mount its unique volume
            # read-only into the execution container. Submission source is never an argv value.
            stager = self.client.containers.create(
                image=IMAGE,
                command=["sleep", "30"],
                network_mode="none",
                volumes={volume.name: {"bind": "/stage", "mode": "rw"}},
                labels=labels,
                log_config={"type": "none"},
                detach=True,
            )
            stager.start()
            archive_buffer = io.BytesIO()
            with tarfile.open(fileobj=archive_buffer, mode="w") as archive:
                for name, payload in (("main.py", source_code.encode("utf-8")), ("input.txt", input_data.encode("utf-8"))):
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    info.mode = 0o444
                    archive.addfile(info, io.BytesIO(payload))
            if not stager.put_archive("/stage", archive_buffer.getvalue()):
                raise RuntimeError("Docker failed to stage submission files")
            stager.remove(force=True)
            stager = None

            container = self.client.containers.create(
                image=IMAGE,
                command=["python", "-I", "-c", compile_and_run],
                network_mode="none",
                mem_limit="128m",
                nano_cpus=500_000_000,
                pids_limit=64,
                read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=16m"},
                user="65534:65534",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                log_config={"type": "none"},
                volumes={volume.name: {"bind": "/submission", "mode": "ro"}},
                labels=labels,
                detach=True,
            )
            output_stream = container.attach(stream=True, logs=False, stdout=True, stderr=True, demux=True)
            started = time.monotonic()
            container.start()

            def capture_output():
                try:
                    for stdout_chunk, stderr_chunk in output_stream:
                        with output_lock:
                            if stdout_chunk:
                                remaining = OUTPUT_LIMIT - len(output)
                                output.extend(stdout_chunk[:max(0, remaining)])
                                if len(stdout_chunk) > remaining:
                                    overflow.set()
                                    try:
                                        container.kill()
                                    except docker.errors.NotFound:
                                        pass
                            if stderr_chunk:
                                remaining = OUTPUT_LIMIT - len(diagnostics)
                                diagnostics.extend(stderr_chunk[:max(0, remaining)])
                except Exception as exc:
                    if not overflow.is_set():
                        log_errors.append(exc)

            log_thread = threading.Thread(target=capture_output, daemon=True)
            log_thread.start()
            deadline = started + (timeout_seconds or self.timeout_seconds)
            while time.monotonic() < deadline:
                container.reload()
                if container.status in {"exited", "dead"} or overflow.is_set():
                    break
                time.sleep(0.05)
            else:
                timed_out = True
            if timed_out:
                try:
                    container.kill()
                except docker.errors.NotFound:
                    pass
            try:
                container.wait(timeout=3)
            except Exception:
                pass
            log_thread.join(timeout=3)
            if log_errors:
                raise RuntimeError(f"Docker output capture failed: {type(log_errors[0]).__name__}") from log_errors[0]
            container.reload()
            exit_code = (container.attrs.get("State") or {}).get("ExitCode", 1)
        finally:
            for temporary in (stager, container):
                if temporary is not None:
                    try:
                        temporary.remove(force=True)
                    except docker.errors.NotFound:
                        pass
            try:
                volume.remove(force=True)
            except docker.errors.NotFound:
                pass

        elapsed = int((time.monotonic() - started) * 1000)
        if timed_out:
            return CaseResult("TIME_LIMIT_EXCEEDED", output.decode("utf-8", "replace"), "", elapsed)
        if overflow.is_set():
            return CaseResult("RUNTIME_ERROR", output.decode("utf-8", "replace"), "stdout exceeded 64 KB", elapsed)
        decoded_diagnostics = diagnostics.decode("utf-8", "replace")
        if exit_code == 86 and compile_failure_marker in decoded_diagnostics:
            return CaseResult("COMPILATION_ERROR", output.decode("utf-8", "replace"), decoded_diagnostics, elapsed)
        if exit_code != 0:
            return CaseResult("RUNTIME_ERROR", output.decode("utf-8", "replace"), decoded_diagnostics, elapsed)
        return CaseResult("ACCEPTED", output.decode("utf-8", "replace"), decoded_diagnostics, elapsed)


def judge_submission(runner: DockerPythonRunner, source_code: str, cases: list[dict], timeout_seconds: float) -> tuple[str, int, int, str, str, list[dict]]:
    total_ms = 0
    case_results = []
    for ordinal, case in enumerate(cases, start=1):
        result = runner.run_case(source_code, case["input_data"], timeout_seconds)
        total_ms += result.execution_time_ms
        case_verdict = result.verdict
        if case_verdict == "ACCEPTED" and result.stdout.strip() != case["expected_output"].strip():
            case_verdict = "WRONG_ANSWER"
        case_results.append({
            "test_case_id": case["id"],
            "ordinal": ordinal,
            "verdict": case_verdict,
            "execution_time_ms": result.execution_time_ms,
        })
        diagnostic = (
            f"case_id={case['id']} hidden={bool(case['is_hidden'])}\n"
            f"input={case['input_data']!r}\nexpected={case['expected_output']!r}\n"
            f"actual={result.stdout!r}\nstderr={result.stderr!r}"
        )
        diagnostic = diagnostic.encode("utf-8")[:60 * 1024].decode("utf-8", "ignore")
        if case_verdict != "ACCEPTED":
            message = "The answer is incorrect." if case_verdict == "WRONG_ANSWER" else "The program did not pass all tests."
            return case_verdict, 0, total_ms, message, diagnostic, case_results
    return "ACCEPTED", 100, total_ms, "Accepted.", None, case_results
