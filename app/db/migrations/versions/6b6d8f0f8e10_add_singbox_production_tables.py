"""singbox production tables

Revision ID: 6b6d8f0f8e10
Revises: 2b231de97dc3
Create Date: 2026-07-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6b6d8f0f8e10'
down_revision = '2b231de97dc3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    node_name_type = sa.String(
        length=256,
        collation=('NOCASE' if op.get_bind().engine.name == 'sqlite' else ''),
    )

    op.create_table(
        'singbox_nodes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', node_name_type, nullable=False),
        sa.Column('public_host', sa.String(length=256), nullable=False),
        sa.Column('entry_enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('exit_enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('node_link_port', sa.Integer(), server_default='12443', nullable=False),
        sa.Column('public_ports', sa.JSON(), nullable=True),
        sa.Column('deploy_method', sa.String(length=32), server_default='manual', nullable=False),
        sa.Column('ssh_host', sa.String(length=256), nullable=True),
        sa.Column('ssh_user', sa.String(length=64), nullable=True),
        sa.Column('ssh_port', sa.Integer(), nullable=True),
        sa.Column('config_path', sa.String(length=512), nullable=False),
        sa.Column('restart_command', sa.String(length=512), nullable=True),
        sa.Column('public_tls_cert_path', sa.String(length=512), nullable=True),
        sa.Column('public_tls_key_path', sa.String(length=512), nullable=True),
        sa.Column('node_link_ca_cert_path', sa.String(length=512), nullable=True),
        sa.Column('node_link_cert_path', sa.String(length=512), nullable=True),
        sa.Column('node_link_key_path', sa.String(length=512), nullable=True),
        sa.Column('node_link_client_cert_path', sa.String(length=512), nullable=True),
        sa.Column('node_link_client_key_path', sa.String(length=512), nullable=True),
        sa.Column('node_link_cert_expires_at', sa.DateTime(), nullable=True),
        sa.Column('node_link_mtls_enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=True),
        sa.Column('message', sa.String(length=1024), nullable=True),
        sa.Column('last_config_hash', sa.String(length=64), nullable=True),
        sa.Column('applied_config_hash', sa.String(length=64), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('usage_coefficient', sa.Float(), server_default=sa.text('1.0'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'singbox_node_links',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('from_node_id', sa.Integer(), nullable=False),
        sa.Column('to_node_id', sa.Integer(), nullable=False),
        sa.Column('protocol', sa.String(length=32), server_default='hysteria2', nullable=False),
        sa.Column('auth_name', sa.String(length=128), nullable=False),
        sa.Column('password', sa.String(length=256), nullable=False),
        sa.Column('mtls_enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('client_cert_expires_at', sa.DateTime(), nullable=True),
        sa.Column('last_rotated_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['from_node_id'], ['singbox_nodes.id']),
        sa.ForeignKeyConstraint(['to_node_id'], ['singbox_nodes.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('from_node_id', 'to_node_id'),
    )

    op.create_table(
        'singbox_user_credentials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('password', sa.String(length=256), nullable=False),
        sa.Column('vmess_uuid', sa.String(length=36), nullable=False),
        sa.Column('vless_uuid', sa.String(length=36), nullable=False),
        sa.Column('tuic_uuid', sa.String(length=36), nullable=False),
        sa.Column('shadowsocks_password', sa.String(length=256), nullable=False),
        sa.Column('enabled_protocols', sa.JSON(), nullable=False),
        sa.Column('exit_node_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['exit_node_id'], ['singbox_nodes.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )

    op.create_table(
        'singbox_route_policies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('entry_node_id', sa.Integer(), nullable=False),
        sa.Column('exit_node_id', sa.Integer(), nullable=True),
        sa.Column('priority', sa.Integer(), server_default='100', nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['entry_node_id'], ['singbox_nodes.id']),
        sa.ForeignKeyConstraint(['exit_node_id'], ['singbox_nodes.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'entry_node_id'),
    )

    op.create_table(
        'singbox_node_usages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=True),
        sa.Column('uplink', sa.BigInteger(), nullable=True),
        sa.Column('downlink', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['node_id'], ['singbox_nodes.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('created_at', 'node_id'),
    )


def downgrade() -> None:
    op.drop_table('singbox_node_usages')
    op.drop_table('singbox_route_policies')
    op.drop_table('singbox_user_credentials')
    op.drop_table('singbox_node_links')
    op.drop_table('singbox_nodes')
