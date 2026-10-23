import argparse
import base64
import hashlib
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

# Ensure repository root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from typing import Any

from plant_definitions import PlantDefinition, load_plants

logger = logging.getLogger("mosquitto_auth")

USERNAME_REGEX = re.compile(r"^[a-z0-9_]{3,64}$")
PLANT_ID_REGEX = re.compile(r"^[a-z0-9_]{3,57}$")


def is_valid_username(username: str) -> bool:
    return bool(username and USERNAME_REGEX.fullmatch(username))


def is_valid_plant_id(plant_id: str) -> bool:
    return bool(plant_id and PLANT_ID_REGEX.fullmatch(plant_id))


def is_valid_password(password: str) -> bool:
    if not password:
        return False
    if any(c in password for c in ("\n", "\r")):
        return False
    for ch in password:
        if ord(ch) < 32 or (127 <= ord(ch) <= 159):
            return False
    return True


def _write_auth_file_atomic(dest_path: Path, content: str) -> None:
    """Write content to a .tmp file and atomically rename, setting 1883:1883 + 0600 or 0644."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(".tmp")
    tmp_path.write_text(content, encoding="utf-8")

    try:
        import pwd

        m_entry = pwd.getpwnam("mosquitto")
        os.chown(tmp_path, m_entry.pw_uid, m_entry.pw_gid)
    except (KeyError, PermissionError, OSError):
        try:
            os.chown(tmp_path, 1883, 1883)
        except (PermissionError, OSError):
            pass

    try:
        os.chmod(tmp_path, 0o600)
    except (PermissionError, OSError):
        os.chmod(tmp_path, 0o644)

    os.replace(tmp_path, dest_path)


def hash_password_pbkdf2(password: str, iterations: int = 101) -> str:
    """Generate Mosquitto-compatible sha512-pbkdf2 password hash ($7$...)."""
    salt = os.urandom(12)
    b64_salt = base64.b64encode(salt).decode("ascii")
    digest = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, iterations)
    b64_digest = base64.b64encode(digest).decode("ascii")
    return f"$7${iterations}${b64_salt}${b64_digest}"


def hash_password(password: str) -> str:
    """Hash password using mosquitto_passwd binary if available, else python pbkdf2."""
    return hash_password_pbkdf2(password)


def generate_acl_content(
    plants: dict[str, PlantDefinition],
    backend_user: str = "backend_service",
) -> str:
    """Generate Mosquitto ACL file content strictly scoping topics by plant_id."""
    if not is_valid_username(backend_user):
        raise ValueError(f"Invalid backend MQTT username: {backend_user}")

    lines: list[str] = [
        "# PlantPulse Mosquitto ACL Configuration",
        "# Auto-generated from plant definitions. Do not edit manually.",
        "",
        "# Backend Service (Full Read/Write Access across all plants)",
        f"user {backend_user}",
        "topic readwrite plants/#",
        "",
    ]

    for plant_id in sorted(plants.keys()):
        plant = plants[plant_id]
        if not is_valid_plant_id(plant.plant_id):
            logger.warning(
                "Skipping invalid plant_id '%s' in ACL generation", plant.plant_id
            )
            continue
        lines.append(f"# Plant: {plant.plant_id}")
        for cred in plant.mqtt_credentials:
            if not is_valid_username(cred.username):
                logger.warning(
                    "Skipping invalid username '%s' for plant '%s' in ACL generation",
                    cred.username,
                    plant.plant_id,
                )
                continue
            if cred.password is not None and not is_valid_password(cred.password):
                logger.warning(
                    "Skipping user '%s' with invalid password from ACL for plant '%s'",
                    cred.username,
                    plant.plant_id,
                )
                continue
            lines.append(f"user {cred.username}")
            lines.append(f"topic readwrite plants/{plant.plant_id}/#")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def generate_auth_files(
    plants_dir: Path,
    passwd_path: Path,
    acl_path: Path,
    backend_user: str = "backend_service",
    backend_password: str | None = None,
) -> tuple[Path, Path]:
    """Generate Mosquitto password and ACL files from plants/*.json."""
    if not is_valid_username(backend_user):
        raise ValueError(f"Invalid backend MQTT username: {backend_user}")
    if not backend_password or not is_valid_password(backend_password):
        raise ValueError(
            "Backend MQTT password is required and must not contain control characters (backend_password). Refusing to generate authentication with missing secret."
        )

    plants = load_plants(plants_dir)

    # 1. Generate ACL file
    acl_content = generate_acl_content(plants, backend_user=backend_user)
    _write_auth_file_atomic(acl_path, acl_content)

    # 2. Generate password file
    passwd_lines: list[str] = []
    passwd_lines.append(f"{backend_user}:{hash_password(backend_password)}")

    for plant in sorted(plants.values(), key=lambda p: p.plant_id):
        if not is_valid_plant_id(plant.plant_id):
            logger.warning(
                "Skipping invalid plant_id '%s' in passwd generation", plant.plant_id
            )
            continue
        for cred in plant.mqtt_credentials:
            if not is_valid_username(cred.username):
                logger.warning(
                    "Skipping invalid username '%s' for plant '%s' in passwd generation",
                    cred.username,
                    plant.plant_id,
                )
                continue
            pwd = cred.password
            if not pwd:
                raise ValueError(
                    f"Missing MQTT password for device '{cred.username}' (plant '{plant.plant_id}'). "
                    f"Configure DEVICE_{cred.username.upper()}_PASSWORD or appropriate environment variable."
                )
            if not is_valid_password(pwd):
                logger.warning(
                    "Skipping invalid password for device '%s' (plant '%s')",
                    cred.username,
                    plant.plant_id,
                )
                continue
            passwd_lines.append(f"{cred.username}:{hash_password(pwd)}")

    _write_auth_file_atomic(passwd_path, "\n".join(passwd_lines) + "\n")

    return passwd_path, acl_path


def reload_mosquitto() -> bool:
    """Send SIGHUP to mosquitto process in shared PID namespace or host process table."""
    pids: list[int] = []
    proc = Path("/proc")
    if proc.exists() and proc.is_dir():
        try:
            for entry in proc.iterdir():
                if entry.name.isdigit():
                    try:
                        comm_file = entry / "comm"
                        if (
                            comm_file.exists()
                            and comm_file.read_text(encoding="utf-8").strip()
                            == "mosquitto"
                        ):
                            pids.append(int(entry.name))
                    except (PermissionError, FileNotFoundError, ProcessLookupError):
                        continue
        except (PermissionError, OSError):
            pass

    if not pids and shutil.which("pgrep"):
        res = subprocess.run(
            ["pgrep", "mosquitto"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            pids = [int(p) for p in res.stdout.strip().splitlines() if p.isdigit()]

    if not pids:
        return False

    signaled = False
    for pid in pids:
        try:
            os.kill(pid, signal.SIGHUP)
            signaled = True
        except (PermissionError, ProcessLookupError):
            pass
    return signaled


_BACKEND_HASH_CACHE: dict[tuple[str, str], str] = {}


def _get_cached_backend_hash(backend_user: str, backend_password: str) -> str:
    if backend_password.startswith("$7$"):
        return backend_password
    key = (backend_user, backend_password)
    if key not in _BACKEND_HASH_CACHE:
        _BACKEND_HASH_CACHE[key] = hash_password_pbkdf2(backend_password)
    return _BACKEND_HASH_CACHE[key]


def sync_broker_auth_from_db(
    conn: Any,
    auth_dir: Path | str | None = None,
    backend_user: str | None = None,
    backend_password: str | None = None,
    reload: bool = True,
) -> bool:
    """Generate Mosquitto password and ACL files from platform database and reload Mosquitto."""
    if auth_dir is None:
        auth_dir = os.getenv("MOSQUITTO_AUTH_DIR", "/mosquitto/auth")
    auth_dir = Path(auth_dir)

    if backend_user is None:
        backend_user = os.getenv(
            "BACKEND_MQTT_USER", os.getenv("MQTT_USER", "backend_service")
        )
    if backend_password is None:
        backend_password = os.getenv("BACKEND_MQTT_PASSWORD")

    if not backend_user or not is_valid_username(backend_user):
        raise ValueError(f"Invalid backend MQTT username: {backend_user}")

    if not backend_password or not is_valid_password(backend_password):
        raise ValueError(
            "Backend MQTT password is required and must not contain control characters (BACKEND_MQTT_PASSWORD). Refusing to generate authentication with missing secret."
        )

    cur = conn.cursor()
    cur.execute(
        "SELECT plant_id, username, password_hash FROM plant_credentials WHERE is_active = true ORDER BY plant_id, username;"
    )
    cred_rows = cur.fetchall()

    cur.execute("SELECT id, name FROM plants ORDER BY id;")
    plant_rows = cur.fetchall()

    # 1. Build passwd lines
    passwd_lines: list[str] = []
    # Always include backend user
    b_hash = _get_cached_backend_hash(backend_user, backend_password)
    passwd_lines.append(f"{backend_user}:{b_hash}")

    creds_by_plant: dict[str, list[str]] = {}
    for row in cred_rows:
        pid = row["plant_id"]
        u = row["username"]
        h = row["password_hash"]

        if not is_valid_plant_id(pid):
            logger.warning(
                "Skipping invalid plant_id '%s' for credential '%s'",
                pid,
                u,
            )
            continue

        if not is_valid_username(u):
            logger.warning(
                "Skipping invalid username '%s' for plant '%s'",
                u,
                pid,
            )
            continue

        if not h or any(c in h for c in ("\n", "\r")):
            logger.warning(
                "Skipping invalid password_hash for user '%s' in plant '%s'",
                u,
                pid,
            )
            continue

        if not h.startswith("$7$"):
            h = hash_password_pbkdf2(h)
            cur.execute(
                "UPDATE plant_credentials SET password_hash = %s WHERE plant_id = %s AND username = %s;",
                (h, pid, u),
            )
            conn.commit()
        passwd_lines.append(f"{u}:{h}")
        creds_by_plant.setdefault(pid, []).append(u)

    passwd_content = "\n".join(passwd_lines) + "\n"

    # 2. Build ACL content
    acl_lines = [
        "# PlantPulse Mosquitto ACL Configuration",
        "# Auto-generated from platform.db. Do not edit manually.",
        "",
        "# Backend Service (Full Read/Write Access across all plants)",
        f"user {backend_user}",
        "topic readwrite plants/#",
        "",
    ]

    for p in plant_rows:
        pid = p["id"]
        if not is_valid_plant_id(pid):
            logger.warning(
                "Skipping invalid plant_id '%s' in plants table",
                pid,
            )
            continue

        users = creds_by_plant.get(pid, [])
        if users:
            acl_lines.append(f"# Plant: {pid}")
            for u in sorted(users):
                acl_lines.append(f"user {u}")
                acl_lines.append(f"topic readwrite plants/{pid}/#")
            acl_lines.append("")

    acl_content = "\n".join(acl_lines).rstrip() + "\n"

    passwd_file = auth_dir / "passwd"
    acl_file = auth_dir / "acl.conf"

    _write_auth_file_atomic(passwd_file, passwd_content)
    _write_auth_file_atomic(acl_file, acl_content)

    if reload:
        return reload_mosquitto()
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Mosquitto password and ACL files from plant definitions.",
    )
    parser.add_argument(
        "--plants-dir",
        type=Path,
        default=Path("plants"),
        help="Directory containing plant definition JSON files",
    )
    parser.add_argument(
        "--passwd-path",
        type=Path,
        default=Path("/etc/mosquitto/passwd"),
        help="Destination path for mosquitto password file",
    )
    parser.add_argument(
        "--acl-path",
        type=Path,
        default=Path("/etc/mosquitto/acl.conf"),
        help="Destination path for mosquitto ACL file",
    )
    parser.add_argument(
        "--backend-user",
        type=str,
        default="backend_service",
        help="Backend service MQTT username",
    )
    parser.add_argument(
        "--backend-password",
        type=str,
        default=os.getenv("BACKEND_MQTT_PASSWORD")
        or os.getenv("BACKEND_SERVICE_PASSWORD"),
        help="Backend service MQTT password",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Trigger SIGHUP reload of running mosquitto process",
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Generate Mosquitto password and ACL files from database",
    )

    args = parser.parse_args()

    if not args.backend_password:
        parser.error(
            "Backend MQTT password is required (set BACKEND_MQTT_PASSWORD in environment or provide --backend-password). Refusing to proceed with missing secret."
        )

    if args.from_db:
        from db import get_db_connection
        from main import seed_plants_if_empty

        conn = get_db_connection()
        try:
            if args.plants_dir.exists():
                seed_plants_if_empty(conn, args.plants_dir)
            auth_dir = args.passwd_path.parent
            sync_broker_auth_from_db(
                conn,
                auth_dir=auth_dir,
                backend_user=args.backend_user,
                backend_password=args.backend_password,
                reload=args.reload,
            )
            print(f"Generated Mosquitto auth from DB in: {auth_dir}")
            return
        finally:
            conn.close()

    passwd_out, acl_out = generate_auth_files(
        plants_dir=args.plants_dir,
        passwd_path=args.passwd_path,
        acl_path=args.acl_path,
        backend_user=args.backend_user,
        backend_password=args.backend_password,
    )
    print(f"Generated password file: {passwd_out}")
    print(f"Generated ACL file: {acl_out}")

    if args.reload:
        reload_mosquitto()
        print("Sent SIGHUP to mosquitto process")


if __name__ == "__main__":
    main()
