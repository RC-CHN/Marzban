from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from config import SINGBOX_NODE_LINK_CA_DIR


@dataclass(frozen=True)
class IssuedNodeCertificate:
    ca_certificate: str
    node_certificate: str
    node_key: str
    client_certificate: str
    client_key: str
    expires_at: datetime


def ca_paths(ca_dir: str | Path = SINGBOX_NODE_LINK_CA_DIR) -> tuple[Path, Path]:
    root = Path(ca_dir)
    return root / "root-ca.crt", root / "root-ca.key"


def ca_status(ca_dir: str | Path = SINGBOX_NODE_LINK_CA_DIR) -> dict:
    ca_crt, ca_key = ca_paths(ca_dir)
    return {
        "ca_dir": str(Path(ca_dir)),
        "certificate_exists": ca_crt.exists(),
        "key_exists": ca_key.exists(),
        "certificate_path": str(ca_crt),
        "key_path": str(ca_key),
    }


def ensure_ca(ca_dir: str | Path = SINGBOX_NODE_LINK_CA_DIR, days: int = 3650) -> dict:
    ca_crt, ca_key = ca_paths(ca_dir)
    ca_crt.parent.mkdir(parents=True, exist_ok=True)
    if not ca_crt.exists() or not ca_key.exists():
        _run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:4096",
                "-keyout",
                str(ca_key),
                "-out",
                str(ca_crt),
                "-days",
                str(days),
                "-nodes",
                "-subj",
                "/CN=Marzban Node Link CA",
            ]
        )
        ca_key.chmod(0o600)
    return ca_status(ca_dir)


def issue_node_certificate(
    node_name: str,
    public_host: str,
    *,
    ca_dir: str | Path = SINGBOX_NODE_LINK_CA_DIR,
    days: int = 365,
) -> IssuedNodeCertificate:
    ensure_ca(ca_dir)
    ca_crt, ca_key = ca_paths(ca_dir)
    issued_dir = Path(ca_dir) / "issued" / node_name
    issued_dir.mkdir(parents=True, exist_ok=True)

    node_crt, node_key = issued_dir / "node.crt", issued_dir / "node.key"
    client_crt, client_key = issued_dir / "client.crt", issued_dir / "client.key"
    _issue_leaf(
        ca_crt,
        ca_key,
        common_name=node_name,
        cert_path=node_crt,
        key_path=node_key,
        days=days,
        ext_text=f"subjectAltName=DNS:{public_host},DNS:{node_name}\nextendedKeyUsage=serverAuth\n",
    )
    _issue_leaf(
        ca_crt,
        ca_key,
        common_name=f"{node_name}-client",
        cert_path=client_crt,
        key_path=client_key,
        days=days,
        ext_text="extendedKeyUsage=clientAuth\n",
    )
    return IssuedNodeCertificate(
        ca_certificate=ca_crt.read_text(),
        node_certificate=node_crt.read_text(),
        node_key=node_key.read_text(),
        client_certificate=client_crt.read_text(),
        client_key=client_key.read_text(),
        expires_at=datetime.utcnow() + timedelta(days=days),
    )


def _issue_leaf(
    ca_crt: Path,
    ca_key: Path,
    *,
    common_name: str,
    cert_path: Path,
    key_path: Path,
    days: int,
    ext_text: str,
) -> None:
    csr_path = cert_path.with_suffix(".csr")
    ext_path = cert_path.with_suffix(".ext")
    _run(
        [
            "openssl",
            "req",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(csr_path),
            "-nodes",
            "-subj",
            f"/CN={common_name}",
        ]
    )
    key_path.chmod(0o600)
    ext_path.write_text(ext_text)
    _run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr_path),
            "-CA",
            str(ca_crt),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(cert_path),
            "-days",
            str(days),
            "-sha256",
            "-extfile",
            str(ext_path),
        ]
    )


def _run(cmd: list[str]) -> None:
    result = subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or f"Command failed: {cmd[0]}")
