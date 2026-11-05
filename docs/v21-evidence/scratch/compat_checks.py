"""Read-only consumer compatibility checks against a scratch Omnigent stack."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

BROKER_PATH = Path("/home/coder/personal/trio-agent-loop/omnigent/broker_http.py")
APP_BUILD = Path("/home/coder/personal/agent-platform/template/build")
ROLES_SRC = Path(
    os.path.expanduser("~/.local/share/trio-agent-loop/current/omnigent/trio-omnigent-roles")
)
FORBIDDEN_PORTS = {6767, 6768, 7456, 8443}

violations = 0
results: list[tuple[str, bool, str]] = []


def emit(name: str, ok: bool, reason: str = "") -> None:
    if ok:
        print(f"CHECK {name}: PASS", flush=True)
        results.append((name, True, ""))
    else:
        print(f"CHECK {name}: FAIL {reason}", flush=True)
        results.append((name, False, reason))


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _url_of(req: Any) -> str:
    if isinstance(req, urllib.request.Request):
        return req.full_url
    if isinstance(req, str):
        return req
    return str(req)


def install_guard(scratch_port: int) -> None:
    orig_urlopen = urllib.request.urlopen
    orig_opener_open = urllib.request.OpenerDirector.open

    def check(url: str) -> None:
        global violations
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port is None:
            port = 80 if parsed.scheme == "http" else 443
        if host != "127.0.0.1" or port != scratch_port:
            violations += 1
            print(f"GUARD_REFUSE host={host!r} port={port} url={url!r}", flush=True)
            raise RuntimeError(f"guarded opener refused host={host!r} port={port} url={url!r}")
        if port in FORBIDDEN_PORTS:
            violations += 1
            raise RuntimeError(f"guarded opener refused forbidden port {port}")

    def wrapped_urlopen(url, data=None, timeout=None, *args, **kwargs):
        check(_url_of(url))
        return orig_urlopen(url, data, timeout, *args, **kwargs)

    def wrapped_open(self, fullurl, data=None, timeout=None):
        check(_url_of(fullurl))
        return orig_opener_open(self, fullurl, data, timeout)

    urllib.request.urlopen = wrapped_urlopen  # type: ignore[assignment]
    urllib.request.OpenerDirector.open = wrapped_open  # type: ignore[method-assign]


def stub_op_control() -> None:
    for name in ("op_control", "op_runtime", "op_login"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)


def environ_of(pid: int) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return out
    for rec in raw.split(b"\0"):
        if not rec or b"=" not in rec:
            continue
        key, _, val = rec.partition(b"=")
        out[key.decode("utf-8", "replace")] = val.decode("utf-8", "replace")
    return out


def pids_referencing(session_id: str, _data_dir: str = "") -> list[int]:
    found: list[int] = []
    try:
        names = os.listdir("/proc")
    except OSError:
        return found
    needle = session_id.encode("utf-8")
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            raw = Path(f"/proc/{pid}/environ").read_bytes()
        except OSError:
            continue
        if needle in raw:
            found.append(pid)
    return found


def pid_alive(pid: int) -> bool:
    path = Path(f"/proc/{pid}")
    if not path.exists():
        return False
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("State:"):
                return line.split()[1] != "Z"
    except OSError:
        return False
    return True


def ppid_of(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def mutate_yaml(src: Path, dest: Path, *, fn_path: str | None, cwd: str | None) -> None:
    text = src.read_text(encoding="utf-8")
    if fn_path is not None:
        text = text.replace(
            "path: omnigent.inner.nessie.policies.blast_radius",
            f"path: {fn_path}",
        )
    if cwd is not None:
        text = re.sub(r"(?m)^(\s*cwd:\s*).*$", rf"\1{cwd}", text, count=1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def copy_roles(scratch: Path) -> Path:
    dest = scratch / "roles"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ROLES_SRC, dest, dirs_exist_ok=True)
    return dest


def _cmdline(pid: int) -> str:
    try:
        return (
            Path(f"/proc/{pid}/cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode("utf-8", "replace")
        )
    except OSError:
        return ""


def wait_runner(session_id: str, data_dir: str, timeout: float = 45.0) -> int | None:
    deadline = time.time() + timeout
    fallback = None
    while time.time() < deadline:
        for pid in pids_referencing(session_id, data_dir):
            env = environ_of(pid)
            if env.get("OMNIGENT_RUNNER_PRIMARY_SESSION_ID") != session_id:
                continue
            cmd = _cmdline(pid)
            if "_zygote" in cmd:
                return pid
            if fallback is None and "tmux" not in cmd.split():
                fallback = pid
        time.sleep(0.4)
    return fallback


def post_events(client: Any, session_id: str) -> tuple[bool, str]:
    """Trio's /events use is POST (BrokerClient.send_message, input_fence).

    v0.21 has no GET /v1/sessions/{id}/events route (reading is via /items
    and the /stream SSE route), so the events check drives the same POST
    trio sends. 202 = accepted. A 4xx is a FAIL unless it is the session-
    state refusal the server gives a session whose harness already ended
    (scratch HOME has no harness credentials), which still proves the
    route, auth and ownership path; 401/403/404 always FAIL.
    """
    try:
        client.send_message(session_id, "v21 scratch follow-up")
        return True, "POST /events -> 202"
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "status_code", None)
        detail = f"POST /events -> {type(exc).__name__} status={code} {exc}"[:400]
        if isinstance(code, int) and code in {409, 422}:
            return True, detail + " (session-state refusal, route+auth ok)"
        return False, detail


def register_error_body(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None)
    return f"status={status} body={exc}"


def main() -> int:
    scratch = Path(os.environ["V21_SCRATCH_DIR"])
    port = int(os.environ["V21_SCRATCH_PORT"])
    data_dir = os.environ["V21_SCRATCH_DATA"]
    host_pid = int(os.environ["V21_HOST_PID"])
    server_pid = int(os.environ["V21_SERVER_PID"])
    if port in FORBIDDEN_PORTS:
        print(f"refusing forbidden scratch port {port}", file=sys.stderr)
        return 2

    os.environ["HOME"] = str(scratch / "home")
    os.environ.pop("OMNIGENT_TOKEN", None)
    os.environ.pop("OMNIGENT_REMOTE_AUTH_TOKEN", None)
    os.environ["OMNIGENT_URL"] = f"http://127.0.0.1:{port}"
    os.environ["TRIO_OMNIGENT_PROMPT_WAIT"] = "20"
    os.environ["TRIO_OMNIGENT_PROMPT_INTERVAL"] = "0.4"

    install_guard(port)
    broker = load_module("v21_broker_http", BROKER_PATH)
    stub_op_control()
    titles = load_module("omnigent_titles", APP_BUILD / "omnigent_titles.py")
    devp = load_module("dev_processes", APP_BUILD / "dev_processes.py")
    base = f"http://127.0.0.1:{port}"
    devp._OMNIGENT_SESSIONS = f"{base}/v1/sessions?limit=200&sort_by=updated_at&order=desc"
    devp._OMNIGENT_SESSION = f"{base}/v1/sessions/"

    roles_dir = copy_roles(scratch)
    role_dirs = sorted(p for p in roles_dir.iterdir() if (p / "config.yaml").is_file())
    if not role_dirs:
        emit("trio-broker", False, "no role bundles copied")
        return 1

    agents: dict[str, dict[str, str]] = {}
    builder_session_from_register = ""
    try:
        for role in role_dirs:
            cfg = role / "config.yaml"
            bundle = broker.bundle_agent_dir(cfg)
            rec = broker.register_agent_bundle(bundle, f"v21-scratch-{role.name}")
            agents[role.name] = rec
            if role.name == "builder":
                builder_session_from_register = rec["session_id"]
            broker.update_agent_bundle(rec["session_id"], bundle)
    except Exception as exc:  # noqa: BLE001
        emit("trio-broker", False, f"register/update: {type(exc).__name__}: {exc}")
        agents = {}

    workspace = scratch / "ws"
    workspace.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init"],
        cwd=workspace,
        check=False,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(scratch / "home"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    created: Any = None
    session_id = ""
    prompt_exc = ""
    client = broker.BrokerClient(base_url=base, timeout=30.0)
    if "builder" in agents:
        try:
            created = client.create_session(
                agents["builder"]["agent_id"],
                "glm-5.2-max",
                "v21 scratch ping",
                title="v21-scratch-builder",
                workspace=str(workspace),
                prompt_timeout=20.0,
            )
            session_id = created.get("id") or created.get("session_id") or ""
        except Exception as exc:  # noqa: BLE001
            prompt_exc = f"{type(exc).__name__}"
            session_id = getattr(exc, "session_id", "") or ""
            if not session_id:
                # PromptDeliveryUncertain stores id in args
                args = getattr(exc, "args", ())
                for arg in args:
                    if isinstance(arg, str) and 8 <= len(arg) <= 128:
                        session_id = arg
                        break
            print(f"create_session exception: {prompt_exc}: {exc}", flush=True)

    if not session_id and builder_session_from_register:
        # create_session may have deleted on hard failure; still probe register id
        print("no host-launched session id from create_session", flush=True)

    events_ok = False
    events_note = "no session"
    items_ok = False
    list_ok = False
    get_ok = False
    if session_id:
        try:
            snap = client.get_session(session_id)
            get_ok = isinstance(snap, dict) and (
                snap.get("id") == session_id or snap.get("session_id") == session_id
            )
        except Exception as exc:  # noqa: BLE001
            get_ok = False
            print(f"get_session: {exc}", flush=True)
        events_ok, events_note = post_events(client, session_id)
        print(f"events: {events_note}", flush=True)
        try:
            items = client.get_items(session_id)
            items_ok = items is not None
        except Exception as exc:  # noqa: BLE001
            items_ok = False
            print(f"get_items: {exc}", flush=True)
        try:
            listed = client.list_sessions(limit=50, kind="any")
            rows = listed.get("data") if isinstance(listed, dict) else listed
            if rows is None and isinstance(listed, dict):
                rows = listed.get("sessions")
            ids = []
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    sid = row.get("id") or row.get("session_id")
                    if isinstance(sid, str):
                        ids.append(sid)
            list_ok = session_id in ids
            if not list_ok:
                print(f"list ids={ids[:12]!r}", flush=True)
        except Exception as exc:  # noqa: BLE001
            list_ok = False
            print(f"list_sessions: {exc}", flush=True)

    agent_ids_ok = bool(agents) and all(
        isinstance(v.get("agent_id"), str) and v["agent_id"] for v in agents.values()
    )
    emit(
        "trio-broker",
        bool(agent_ids_ok and session_id and get_ok and events_ok and items_ok and list_ok),
        (
            f"agents={agent_ids_ok} session={bool(session_id)} get={get_ok} "
            f"events={events_ok} items={items_ok} list={list_ok} "
            f"prompt_exc={prompt_exc} note={events_note}"
        )
        if not (agent_ids_ok and session_id and get_ok and events_ok and items_ok and list_ok)
        else "",
    )

    # v0.21.0 final (#12711/#12712): ask_on_os_tools now also gates sys_terminal_*.
    # Record which policies a trio-launched session actually runs under (admin +
    # store via GET /v1/sessions/{id}/policies, plus GET /v1/policies defaults);
    # PASS iff neither lists the file & shell approval policy.
    pol_ok = False
    pol_note = "no session"
    if session_id:
        try:
            names: list[str] = []
            for path in (f"/v1/sessions/{session_id}/policies", "/v1/policies"):
                with urllib.request.urlopen(base + path, timeout=15) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                for row in body.get("data", []) if isinstance(body, dict) else []:
                    if isinstance(row, dict):
                        names.append(
                            f"{path.rsplit('/', 1)[-1]}:{row.get('source', '')}:"
                            f"{row.get('name', '')}:{row.get('handler', '')}"
                        )
            pol_note = f"policies={names!r}"
            pol_ok = not any("ask_on_os_tools" in n or "File & Shell" in n for n in names)
        except Exception as exc:  # noqa: BLE001
            pol_note = f"{type(exc).__name__}: {exc}"
    print(f"trio-session-policies: {pol_note}", flush=True)
    emit("trio-session-policies", pol_ok, "" if pol_ok else pol_note)

    # --- bundle-restrictions-10906 ---
    def expect_4xx(label: str, cfg: Path) -> tuple[bool, str]:
        try:
            broker.register_agent_bundle(broker.bundle_agent_dir(cfg), label)
            return False, f"{label}: accepted unmodified-path error"
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "status_code", None)
            detail = register_error_body(exc)
            print(f"{label}: {detail}", flush=True)
            ok = isinstance(code, int) and 400 <= code < 500
            return ok, detail if ok else f"{label} not 4xx: {detail}"

    bad_fn = scratch / "bad-fn" / "config.yaml"
    bad_abs = scratch / "bad-abs" / "config.yaml"
    bad_dot = scratch / "bad-dot" / "config.yaml"
    builder_cfg = roles_dir / "builder" / "config.yaml"
    mutate_yaml(builder_cfg, bad_fn, fn_path="os.system", cwd=None)
    mutate_yaml(builder_cfg, bad_abs, fn_path=None, cwd="/tmp")
    mutate_yaml(builder_cfg, bad_dot, fn_path=None, cwd="../x")
    ok_fn, d_fn = expect_4xx("unregistered-fn", bad_fn)
    ok_abs, d_abs = expect_4xx("cwd-abs", bad_abs)
    ok_dot, d_dot = expect_4xx("cwd-dotdot", bad_dot)
    unmodified_ok = agent_ids_ok
    emit(
        "bundle-restrictions-10906",
        ok_fn and ok_abs and ok_dot and unmodified_ok,
        f"fn={d_fn}; abs={d_abs}; dot={d_dot}; unmodified={unmodified_ok}"
        if not (ok_fn and ok_abs and ok_dot and unmodified_ok)
        else "",
    )

    # --- ownership-10850 ---
    patch_note = "broker_http has no permission_mode helper; PATCH as owner"
    patch_status = ""
    if session_id:
        try:
            patched = client._request(
                "PATCH",
                f"/v1/sessions/{urllib.parse.quote(session_id, safe='')}",
                {"permission_mode": "plan"},
            )
            patch_status = f"PATCH permission_mode=plan -> {patched!r}"[:400]
        except Exception as exc:  # noqa: BLE001
            patch_status = (
                f"PATCH permission_mode=plan -> {type(exc).__name__} "
                f"status={getattr(exc, 'status_code', None)} {exc}"
            )[:400]
        print(patch_note, flush=True)
        print(patch_status, flush=True)

    runner_pid = wait_runner(session_id, data_dir) if session_id else None
    print(f"runner_pid={runner_pid} session_id={session_id}", flush=True)

    # --- appcontrol-dev-processes (before DELETE) ---
    ac_reasons: list[str] = []
    ac_ok = True
    log_hex = None
    session_zygotes: list[int] = []
    if runner_pid is None:
        ac_ok = False
        ac_reasons.append("no runner pid before DELETE")
    else:
        procs = devp._scan("/proc")
        for pid in pids_referencing(session_id, data_dir):
            proc = procs.get(pid)
            argv = list(proc.argv) if proc is not None else []
            print(f"session pid={pid} argv={argv[:8]!r} ppid={ppid_of(pid)}", flush=True)
            try:
                fd_dir = Path(f"/proc/{pid}/fd")
                links = []
                for name in sorted(fd_dir.iterdir(), key=lambda p: p.name)[:24]:
                    try:
                        links.append(os.readlink(name))
                    except OSError:
                        continue
                print(f"  fds={links!r}", flush=True)
            except OSError as exc:
                print(f"  fds error: {exc}", flush=True)
            hex_try = devp._zygote_log_session_id("/proc", pid)
            print(f"  _zygote_log_session_id({pid})={hex_try!r}", flush=True)
            if hex_try and log_hex is None:
                log_hex = hex_try
                runner_pid = pid

        def _reaches_host(pid: int) -> bool:
            cursor = pid
            for _ in range(24):
                if cursor == host_pid:
                    return True
                nxt = ppid_of(cursor)
                if nxt is None or nxt <= 1:
                    return False
                cursor = nxt
            return False

        zygote_pids = [
            p.pid for p in procs.values() if devp._is_zygote_proc(p) and _reaches_host(p.pid)
        ]
        print(f"scratch-host zygote pids={zygote_pids}", flush=True)
        for zpid in zygote_pids:
            hex_try = devp._zygote_log_session_id("/proc", zpid)
            print(f"  zygote {zpid} log_hex={hex_try!r} ppid={ppid_of(zpid)}", flush=True)
            if hex_try == session_id:
                log_hex = hex_try
                runner_pid = zpid
                session_zygotes.append(zpid)
        print(f"_zygote_log_session_id chosen={log_hex!r} runner_pid={runner_pid}", flush=True)
        if not (isinstance(log_hex, str) and re.fullmatch(r"[0-9a-f]{32}", log_hex)):
            ac_ok = False
            ac_reasons.append(f"log hex {log_hex!r} not 32-hex")
        elif log_hex != session_id:
            ac_ok = False
            ac_reasons.append(f"log hex {log_hex} != session id {session_id}")
        else:
            print(f"log hex relation: equal to API session id {session_id}", flush=True)
        env_allow = {}
        env_pid = None
        for pid in pids_referencing(session_id, data_dir):
            env = devp._read_environ("/proc", pid)
            print(f"_read_environ({pid})={env!r}", flush=True)
            if env.get("OMNIGENT_RUNNER_PRIMARY_SESSION_ID") == session_id:
                env_allow = env
                env_pid = pid
                if env.get("OMNIGENT_RUNNER_WORKSPACE") == str(workspace):
                    break
        print(f"_read_environ chosen pid={env_pid} {env_allow!r}", flush=True)
        if env_allow.get("OMNIGENT_RUNNER_PRIMARY_SESSION_ID") != session_id:
            ac_ok = False
            ac_reasons.append("PRIMARY_SESSION_ID mismatch")
        if env_allow.get("OMNIGENT_RUNNER_WORKSPACE") != str(workspace):
            ac_ok = False
            ac_reasons.append(
                f"WORKSPACE {env_allow.get('OMNIGENT_RUNNER_WORKSPACE')!r} != {str(workspace)!r}"
            )
        procs = devp._scan("/proc")
        runner_proc = procs.get(runner_pid)
        zygotes = [p for p in procs.values() if devp._is_zygote_proc(p)]
        runner_is_zygote = runner_proc is not None and devp._is_zygote_proc(runner_proc)
        ancestor_zygote = False
        cursor = runner_pid
        for _ in range(24):
            proc = procs.get(cursor)
            if proc is not None and devp._is_zygote_proc(proc):
                ancestor_zygote = True
            nxt = ppid_of(cursor)
            if nxt is None or nxt <= 1:
                break
            cursor = nxt
        if not runner_is_zygote:
            print(
                f"note: runner argv has no _zygote; ancestor_zygote={ancestor_zygote}",
                flush=True,
            )
            if not ancestor_zygote:
                ac_ok = False
                ac_reasons.append("runner _is_zygote_proc is false")
        zygote_true = any(devp._is_zygote_proc(z) for z in zygotes) or ancestor_zygote
        if not zygote_true:
            ac_ok = False
            ac_reasons.append("no zygote proc")
        chain_ok = False
        cursor = runner_pid
        for _ in range(24):
            if cursor == host_pid:
                chain_ok = True
                break
            nxt = ppid_of(cursor)
            if nxt is None or nxt <= 1:
                break
            cursor = nxt
        if not chain_ok:
            ac_ok = False
            ac_reasons.append("ppid chain did not reach host pid")
        harness = []
        for pid, proc in procs.items():
            env = proc.environ or {}
            hid = env.get("OMNIGENT_TERMINAL_LAUNCH_SESSION_ID")
            prim = env.get("OMNIGENT_RUNNER_PRIMARY_SESSION_ID")
            if hid == session_id or prim == session_id:
                harness.append(pid)
        print(f"session-linked pids={harness}", flush=True)
        try:
            snap = devp.snapshot(
                proc_root="/proc",
                home=str(scratch / "home"),
                docker=False,
                omnigent_fetch=lambda: titles.http_fetch_list(base=base, limit=50) or [],
            )
            print(f"snapshot type={type(snap).__name__}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"snapshot optional error: {type(exc).__name__}: {exc}", flush=True)
    log_dir = Path(data_dir) / "logs" / "runner"
    names = []
    if log_dir.is_dir():
        names = sorted(p.name for p in log_dir.iterdir())
    print(f"runner log basenames={names}", flush=True)
    rx = re.compile(r"^runner-([0-9a-f]{32})-\d{8}-\d{6}-\d+\.log$")
    matched_logs = [n for n in names if rx.match(n)]
    print(f"runner logs matching App Control regex={matched_logs}", flush=True)
    emit("appcontrol-dev-processes", ac_ok, "; ".join(ac_reasons))

    # --- appcontrol-titles ---
    title_ok = False
    title_reason = "no session"
    api_title = ""
    if session_id:
        try:
            api = client.get_session(session_id)
            api_title = api.get("title") if isinstance(api, dict) else ""
        except Exception as exc:  # noqa: BLE001
            title_reason = f"api get: {exc}"
            api = None
        one = titles.http_fetch_one(session_id, base=base)
        lst = titles.http_fetch_list(base=base, limit=100)
        one_id = one.get("id") if isinstance(one, dict) else None
        one_title = one.get("title") if isinstance(one, dict) else None
        list_hit = None
        if isinstance(lst, list):
            for item in lst:
                if isinstance(item, dict) and item.get("id") == session_id:
                    list_hit = item
                    break
        print(
            f"http_fetch_one={one!r} list_hit={list_hit!r} api_title={api_title!r}",
            flush=True,
        )
        title_ok = (
            one_id == session_id
            and list_hit is not None
            and list_hit.get("id") == session_id
            and (one_title == api_title or list_hit.get("title") == api_title)
        )
        if not title_ok:
            title_reason = (
                f"one_id={one_id!r} list={list_hit} api_title={api_title!r} "
                f"one_title={one_title!r}"
            )
    emit("appcontrol-titles", title_ok, title_reason if not title_ok else "")

    # --- runner-gone-after-delete ---
    gone_ok = False
    gone_reason = "no session/runner"
    tracked = []
    delete_ok = False
    if session_id:
        tracked = pids_referencing(session_id, data_dir)
        # every zygote-forked process holding this session's runner log fd
        for zpid in [runner_pid, *session_zygotes] if log_hex == session_id else []:
            if zpid is not None and zpid not in tracked:
                tracked.append(zpid)
        print(
            f"pre-delete session pids={tracked} (runner pid={runner_pid}, "
            f"session zygotes={session_zygotes})",
            flush=True,
        )
        # trioctl's real close (installed release omnigent/trioctl `_stop_session_runner`,
        # called right before `_delete_session_checked_detail`): PATCH archived=true so the
        # server sends the host `stop_runner`, poll GET until runner_online is false (<=20 s),
        # then DELETE. DELETE alone does not stop a host-launched session's runner on v0.21
        # (upstream route; the fork does not touch it) -- trioctl documents the same.
        archive_ok = False
        offline = None
        try:
            client.archive_session(session_id)
            archive_ok = True
            deadline_a = time.time() + 20
            while time.time() < deadline_a:
                snap_a = client.get_session(session_id)
                offline = snap_a.get("runner_online") if isinstance(snap_a, dict) else None
                if offline is False:
                    break
                time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001
            print(f"archive_session: {type(exc).__name__} {exc}", flush=True)
        print(f"archive -> ok={archive_ok} runner_online={offline}", flush=True)
        try:
            client.delete_session(session_id)
            delete_ok = True
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "status_code", None)
            delete_ok = isinstance(code, int) and 200 <= code < 300
            print(f"delete_session: {type(exc).__name__} {exc}", flush=True)
        if delete_ok:
            deadline = time.time() + 60
            leftover: list[int] = []
            while time.time() < deadline:
                # tracked pids (incl. the runner) plus any new session-env pids
                leftover = sorted(
                    {p for p in tracked if pid_alive(p)}
                    | {p for p in pids_referencing(session_id, data_dir) if pid_alive(p)}
                )
                if not leftover:
                    break
                sleep_left = deadline - time.time()
                time.sleep(0.5 if sleep_left > 0.5 else max(sleep_left, 0.05))
            server_up = pid_alive(server_pid)
            host_up = pid_alive(host_pid)
            runner_tracked = runner_pid in tracked
            gone_ok = not leftover and server_up and host_up and runner_tracked and archive_ok
            gone_reason = (
                f"leftover={leftover} server_up={server_up} host_up={host_up} "
                f"runner_tracked={runner_tracked} archive_ok={archive_ok}"
            )
            print(f"post-delete leftover={leftover} runner_pid={runner_pid}", flush=True)
        else:
            gone_reason = "DELETE not 2xx"
    emit("runner-gone-after-delete", gone_ok, gone_reason if not gone_ok else "")

    # --- ownership-10850: trio's caller (single-user loopback, no token) created the
    # session, so it is the owner and may read /events (POST), /items and DELETE it.
    owner_ok = bool(session_id and get_ok and events_ok and items_ok and delete_ok)
    emit(
        "ownership-10850",
        owner_ok,
        f"session={session_id!r} get={get_ok} events={events_ok} items={items_ok} "
        f"delete={delete_ok}"
        if not owner_ok
        else "",
    )

    print(f"GUARDED_VIOLATIONS={violations}", flush=True)
    Path(os.environ.get("V21_GUARD_FILE", str(scratch / "guard_count"))).write_text(
        str(violations), encoding="utf-8"
    )
    failed = sum(1 for _, ok, _ in results if not ok)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
