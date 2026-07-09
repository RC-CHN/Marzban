from __future__ import annotations

import shlex
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.core.singbox import ca as singbox_ca
from app.core.singbox.config import config_hash
from app.core.singbox.operations import deploy_node_config
from app.core.singbox.poc import (
    NODES,
    TEST_CASES,
    build_poc_builder,
    build_poc_clash_subscription,
    build_poc_manifest,
    build_poc_singbox_subscription,
)
from app.core.singbox import production
from app.db import Session, crud, get_db
from app.db.models import SingBoxNodeUsage
from app.dependencies import validate_dates
from app.models.admin import Admin
from app.models.singbox import (
    SingBoxDeploymentRequest,
    SingBoxDeploymentResponse,
    SingBoxEnrollmentCreate,
    SingBoxEnrollmentResponse,
    SingBoxNodeEnrollRequest,
    SingBoxNodeEnrollResponse,
    SingBoxNodeCreate,
    SingBoxNodeLinkResponse,
    SingBoxNodeModify,
    SingBoxNodeResponse,
    SingBoxUsageRecord,
    SingBoxUsageReport,
    SingBoxUserPolicyModify,
    SingBoxUserPolicyResponse,
)
from app.utils import responses
from config import (
    SINGBOX_NODE_LINK_MTLS,
)

router = APIRouter(
    tags=["sing-box"],
    prefix="/api/singbox",
    responses={401: responses._401, 403: responses._403},
)


class ExitPolicyRequest(BaseModel):
    entry_node: str = "node-a"
    auth_user: str = "u1"
    exit_node: str | None = None


@router.get("/bootstrap.sh", response_class=PlainTextResponse, include_in_schema=False)
def get_bootstrap_script():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "singbox-bootstrap.sh"
    return script_path.read_text()


@router.get("/status")
def get_status(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    nodes = production.get_nodes(db)
    public_tls_modes = sorted({node.public_tls_mode or "system-ca" for node in nodes})
    return {
        "runtime": "sing-box",
        "public_tls": {
            "mode": public_tls_modes[0] if len(public_tls_modes) == 1 else "node-controlled",
            "modes": public_tls_modes,
            "insecure": any(node.public_tls_mode == "ip-insecure" for node in nodes),
            "ca_configured": any(node.public_tls_mode == "ip-ca" and node.public_tls_ca_cert_path for node in nodes),
        },
        "node_link_tls": {
            "mode": "internal-ca",
            "address_mode": "ip-or-domain",
            "mtls": SINGBOX_NODE_LINK_MTLS,
        },
        "nodes": [
            {
                "id": node.id,
                "name": node.name,
                "status": node.status,
                "entry_enabled": node.entry_enabled,
                "exit_enabled": node.exit_enabled,
                "last_config_hash": node.last_config_hash,
                "applied_config_hash": node.applied_config_hash,
                "last_seen_at": node.last_seen_at,
            }
            for node in nodes
        ],
        "traffic_accounting": "approximate",
    }


@router.get("/ca/status")
def get_ca_status(_: Admin = Depends(Admin.check_sudo_admin)):
    return singbox_ca.ca_status()


@router.post("/ca/init")
def init_ca(_: Admin = Depends(Admin.check_sudo_admin)):
    try:
        return singbox_ca.ensure_ca()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/nodes", response_model=list[SingBoxNodeResponse])
def list_nodes(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    return production.get_nodes(db)


@router.post("/nodes", response_model=SingBoxNodeResponse, responses={409: responses._409})
def create_node(
    payload: SingBoxNodeCreate,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        return production.create_node(db, payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f'Node "{payload.name}" already exists') from exc


@router.post("/nodes/enroll", response_model=SingBoxNodeEnrollResponse, responses={403: responses._403})
def enroll_node(
    payload: SingBoxNodeEnrollRequest,
    db: Session = Depends(get_db),
):
    enrollment = production.get_valid_enrollment(db, payload.token)
    if enrollment is None:
        raise HTTPException(status_code=403, detail="Invalid or expired enrollment token")
    node = enrollment.node
    if node.name != payload.node_name or node.public_host != payload.node_host:
        raise HTTPException(status_code=400, detail="Enrollment token does not match this node")

    try:
        issued = singbox_ca.issue_node_certificate_from_csrs(
            node.name,
            node.public_host,
            node_csr=payload.node_csr,
            client_csr=payload.client_csr,
            public_csr=payload.public_csr,
        )
        config, hash_value = production.build_node_config(db, node.id)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    node.node_link_cert_expires_at = issued.expires_at
    node.last_config_hash = hash_value
    production.consume_enrollment(db, enrollment)
    return SingBoxNodeEnrollResponse(
        node_id=node.id,
        node_name=node.name,
        config_hash=hash_value,
        expires_at=issued.expires_at,
        paths={
            "config_path": node.config_path,
            "public_tls_cert_path": node.public_tls_cert_path,
            "public_tls_key_path": node.public_tls_key_path,
            "public_tls_ca_cert_path": node.public_tls_ca_cert_path,
            "node_link_ca_cert_path": node.node_link_ca_cert_path,
            "node_link_cert_path": node.node_link_cert_path,
            "node_link_key_path": node.node_link_key_path,
            "node_link_client_cert_path": node.node_link_client_cert_path,
            "node_link_client_key_path": node.node_link_client_key_path,
        },
        files={
            "node-link-ca.crt": issued.ca_certificate,
            "node.crt": issued.node_certificate,
            "client.crt": issued.client_certificate,
            "public-ca.crt": issued.ca_certificate,
            "public.crt": issued.public_certificate,
        },
        config=config,
    )


@router.get("/nodes/{node_id}", response_model=SingBoxNodeResponse)
def get_node(
    node_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    node = production.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.put("/nodes/{node_id}", response_model=SingBoxNodeResponse)
def update_node(
    node_id: int,
    payload: SingBoxNodeModify,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    node = production.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return production.update_node(db, node, payload)


@router.post("/nodes/{node_id}/enrollment", response_model=SingBoxEnrollmentResponse)
def create_node_enrollment(
    node_id: int,
    payload: SingBoxEnrollmentCreate,
    request: Request,
    db: Session = Depends(get_db),
    admin: Admin = Depends(Admin.check_sudo_admin),
):
    node = production.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    enrollment, token = production.create_enrollment_token(
        db,
        node,
        expires_in_seconds=payload.expires_in_seconds,
        created_by=admin.username,
    )
    base_url = str(request.base_url).rstrip("/")
    bootstrap_url = f"{base_url}/api/singbox/bootstrap.sh"
    q = shlex.quote
    command = (
        f"curl -fsSL {q(bootstrap_url)} | sudo bash -s -- enroll-node "
        f"--panel-url {q(base_url)} --enroll-token {q(token)} "
        f"--node-name {q(node.name)} --node-host {q(node.public_host)}"
    )
    return SingBoxEnrollmentResponse(
        node_id=node.id,
        node_name=node.name,
        token=token,
        expires_at=enrollment.expires_at,
        bootstrap_url=bootstrap_url,
        command=command,
    )


@router.delete("/nodes/{node_id}")
def delete_node(
    node_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    node = production.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    production.delete_node(db, node)
    return {}


@router.get("/nodes/{node_id}/config")
def get_node_config(
    node_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    try:
        config, hash_value = production.build_node_config(db, node_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"node_id": node_id, "hash": hash_value, "config": config}


@router.post("/nodes/{node_id}/deploy", response_model=SingBoxDeploymentResponse)
def deploy_node(
    node_id: int,
    payload: SingBoxDeploymentRequest,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    node = production.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        config, hash_value = production.build_node_config(db, node_id)
        applied, output = deploy_node_config(node, config, apply=payload.apply and not payload.dry_run)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    production.update_node_config_hash(db, node, hash_value, applied=applied)
    return SingBoxDeploymentResponse(
        node_id=node.id,
        node_name=node.name,
        config_hash=hash_value,
        deploy_method=node.deploy_method,
        checked=node.deploy_method != "manual",
        applied=applied,
        output=output,
    )


@router.post("/deploy", response_model=list[SingBoxDeploymentResponse])
def deploy_all_nodes(
    payload: SingBoxDeploymentRequest,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    responses = []
    for node in production.get_nodes(db):
        try:
            config, hash_value = production.build_node_config(db, node.id)
            applied, output = deploy_node_config(node, config, apply=payload.apply and not payload.dry_run)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"{node.name}: {exc}") from exc
        production.update_node_config_hash(db, node, hash_value, applied=applied)
        responses.append(
            SingBoxDeploymentResponse(
                node_id=node.id,
                node_name=node.name,
                config_hash=hash_value,
                deploy_method=node.deploy_method,
                checked=node.deploy_method != "manual",
                applied=applied,
                output=output,
            )
        )
    return responses


@router.post("/nodes/{node_id}/certificates")
def issue_node_certificates(
    node_id: int,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    node = production.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        issued = singbox_ca.issue_node_certificate(node.name, node.public_host)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    node.node_link_cert_expires_at = issued.expires_at
    db.commit()
    return {
        "node_id": node.id,
        "node_name": node.name,
        "expires_at": issued.expires_at,
        "files": {
            "ca.crt": issued.ca_certificate,
            "node.crt": issued.node_certificate,
            "node.key": issued.node_key,
            "client.crt": issued.client_certificate,
            "client.key": issued.client_key,
        },
    }


@router.get("/links", response_model=list[SingBoxNodeLinkResponse])
def list_links(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    return db.query(production.SingBoxNodeLink).order_by(production.SingBoxNodeLink.id).all()


@router.post("/links/rebuild", response_model=list[SingBoxNodeLinkResponse])
def rebuild_links(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    return production.rebuild_full_mesh_links(db)


@router.post("/links/rotate", response_model=list[SingBoxNodeLinkResponse])
def rotate_links(
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    return production.rotate_node_links(db)


@router.get("/users/{username}/policy", response_model=SingBoxUserPolicyResponse)
def get_user_policy(
    username: str,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    user = crud.get_user(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    credential = production.ensure_user_credentials(db, user)
    return SingBoxUserPolicyResponse(
        username=user.username,
        enabled_protocols=credential.enabled_protocols,
        exit_node_id=credential.exit_node_id,
        has_credentials=True,
    )


@router.put("/users/{username}/policy", response_model=SingBoxUserPolicyResponse)
def update_user_policy(
    username: str,
    payload: SingBoxUserPolicyModify,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    user = crud.get_user(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.exit_node_id is not None and not production.get_node(db, payload.exit_node_id):
        raise HTTPException(status_code=404, detail="Exit node not found")
    current = production.ensure_user_credentials(db, user)
    credential = production.update_user_policy(
        db,
        user,
        enabled_protocols=payload.enabled_protocols
        if "enabled_protocols" in payload.model_fields_set
        else current.enabled_protocols,
        exit_node_id=payload.exit_node_id
        if "exit_node_id" in payload.model_fields_set
        else current.exit_node_id,
    )
    return SingBoxUserPolicyResponse(
        username=user.username,
        enabled_protocols=credential.enabled_protocols,
        exit_node_id=credential.exit_node_id,
        has_credentials=True,
    )


@router.get("/subscription/{username}/sing-box")
def get_admin_singbox_subscription(
    username: str,
    entry_node_id: int | None = None,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    user = crud.get_user(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        config = production.build_user_subscription(db, user, entry_node_id, "sing-box")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"hash": config_hash(config), "config": config}


@router.get("/subscription/{username}/clash", response_class=PlainTextResponse)
def get_admin_clash_subscription(
    username: str,
    entry_node_id: int | None = None,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    user = crud.get_user(db, username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        return production.build_user_subscription(db, user, entry_node_id, "clash")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/usage", response_model=list[SingBoxUsageRecord])
def get_usage(
    db: Session = Depends(get_db),
    start: str = "",
    end: str = "",
    _: Admin = Depends(Admin.check_sudo_admin),
):
    start_dt, end_dt = validate_dates(start, end)
    records = []
    for node in production.get_nodes(db):
        uplink = 0
        downlink = 0
        for usage in (
            db.query(SingBoxNodeUsage)
            .filter(
                SingBoxNodeUsage.node_id == node.id,
                SingBoxNodeUsage.created_at >= start_dt,
                SingBoxNodeUsage.created_at <= end_dt,
            )
            .all()
        ):
            uplink += usage.uplink or 0
            downlink += usage.downlink or 0
        records.append(SingBoxUsageRecord(node_id=node.id, node_name=node.name, uplink=uplink, downlink=downlink))
    return records


@router.post("/nodes/{node_id}/usage", response_model=SingBoxUsageRecord)
def report_node_usage(
    node_id: int,
    payload: SingBoxUsageReport,
    db: Session = Depends(get_db),
    _: Admin = Depends(Admin.check_sudo_admin),
):
    node = production.get_node(db, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    usage = production.record_node_usage(db, node, payload.uplink, payload.downlink)
    return SingBoxUsageRecord(
        node_id=node.id,
        node_name=node.name,
        uplink=usage.uplink or 0,
        downlink=usage.downlink or 0,
    )


@router.get("/poc/topology")
def get_poc_topology(_: Admin = Depends(Admin.check_sudo_admin)):
    """Return the deterministic sing-box POC topology."""
    return build_poc_manifest()


@router.get("/poc/config/{node_name}")
def get_poc_node_config(node_name: str, _: Admin = Depends(Admin.check_sudo_admin)):
    """Render a sing-box node config for the POC topology."""
    if node_name not in NODES:
        raise HTTPException(status_code=404, detail="Node not found")
    builder = build_poc_builder()
    config = builder.build_node_config(node_name)
    return {
        "node": node_name,
        "hash": config_hash(config),
        "config": config,
    }


@router.get("/poc/client/{case_name}")
def get_poc_client_config(case_name: str, _: Admin = Depends(Admin.check_sudo_admin)):
    """Render a sing-box client config for a POC test case."""
    case = TEST_CASES.get(case_name)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    builder = build_poc_builder()
    config = builder.build_client_config(case["protocol"], case["entry"], case["user"])
    return {
        "case": case_name,
        "hash": config_hash(config),
        "config": config,
    }


@router.get("/poc/links")
def get_poc_links(_: Admin = Depends(Admin.check_sudo_admin)):
    """Return generated directed node links for the POC topology."""
    builder = build_poc_builder()
    return {
        "links": [
            {
                "from_node": link.from_node,
                "to_node": link.to_node,
                "protocol": "hysteria2",
                "auth_name": link.auth_name,
                "enabled": link.enabled,
            }
            for link in builder.node_links or []
        ]
    }


@router.post("/poc/links/rebuild")
def rebuild_poc_links(_: Admin = Depends(Admin.check_sudo_admin)):
    """Rebuild the deterministic full-mesh link set used by the POC."""
    builder = build_poc_builder()
    links = builder.build_full_mesh_links()
    return {"links": len(links), "rotated": False}


@router.put("/poc/route-policy")
def preview_poc_route_policy(
    payload: ExitPolicyRequest,
    _: Admin = Depends(Admin.check_sudo_admin),
):
    """Preview a user exit-node policy and the resulting entry node config hash."""
    if payload.entry_node not in NODES:
        raise HTTPException(status_code=404, detail="Entry node not found")
    if payload.exit_node is not None and payload.exit_node not in NODES:
        raise HTTPException(status_code=404, detail="Exit node not found")
    builder = build_poc_builder()
    config = builder.build_node_config(payload.entry_node)
    return {
        "entry_node": payload.entry_node,
        "auth_user": payload.auth_user,
        "exit_node": payload.exit_node,
        "config_hash": config_hash(config),
        "requires_restart": True,
    }


@router.get("/poc/subscription/sing-box")
def get_poc_singbox_subscription(_: Admin = Depends(Admin.check_sudo_admin)):
    """Render the POC sing-box client subscription."""
    config = build_poc_singbox_subscription()
    return {"hash": config_hash(config), "config": config}


@router.get("/poc/subscription/clash", response_class=PlainTextResponse)
def get_poc_clash_subscription(_: Admin = Depends(Admin.check_sudo_admin)):
    """Render the POC Clash/Mihomo subscription."""
    return build_poc_clash_subscription()


@router.get("/poc/status")
def get_poc_status(_: Admin = Depends(Admin.check_sudo_admin)):
    """Return coarse POC node status derived from generated config hashes."""
    manifest = build_poc_manifest()
    return {
        "runtime": "sing-box",
        "nodes": [
            {
                "name": node,
                "status": "generated",
                "config_hash": manifest["node_hashes"][node],
            }
            for node in manifest["nodes"]
        ],
        "traffic_accounting": "approximate",
    }
