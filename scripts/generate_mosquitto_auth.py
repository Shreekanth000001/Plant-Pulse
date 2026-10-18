import argparse
import base64
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from plant_definitions import PlantDefinition, load_plants


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
        lines.append(f"# Plant: {plant.name} ({plant.plant_id})")
        for cred in plant.mqtt_credentials:
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
    plants = load_plants(plants_dir)

    # 1. Generate ACL file
    acl_content = generate_acl_content(plants, backend_user=backend_user)
    acl_path.parent.mkdir(parents=True, exist_ok=True)
    acl_path.write_text(acl_content, encoding="utf-8")
    os.chmod(acl_path, 0o600)

    # 2. Generate password file
    passwd_path.parent.mkdir(parents=True, exist_ok=True)

    # If mosquitto_passwd binary is present, we can use it, or write hashes directly.
    # Writing hashes directly ensures exact 0600 permissions and cross-platform reliability.
    passwd_lines: list[str] = []

    if backend_password:
        passwd_lines.append(f"{backend_user}:{hash_password(backend_password)}")

    for plant in sorted(plants.values(), key=lambda p: p.plant_id):
        for cred in plant.mqtt_credentials:
            passwd_lines.append(f"{cred.username}:{hash_password(cred.password)}")

    passwd_path.write_text("\n".join(passwd_lines) + "\n", encoding="utf-8")
    os.chmod(passwd_path, 0o600)

    return passwd_path, acl_path


def reload_mosquitto() -> None:
    """Send SIGHUP to mosquitto process if running."""
    if shutil.which("pgrep") and shutil.which("kill"):
        res = subprocess.run(
            ["pgrep", "mosquitto"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            for pid in res.stdout.strip().splitlines():
                subprocess.run(["kill", "-HUP", pid], check=False)


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
        default=os.getenv("BACKEND_SERVICE_PASSWORD", "backend_service_secret"),
        help="Backend service MQTT password",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Trigger SIGHUP reload of running mosquitto process",
    )

    args = parser.parse_args()

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
