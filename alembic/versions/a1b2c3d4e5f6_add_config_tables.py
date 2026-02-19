"""add config tables: git_providers, repositories, recipients, app_settings

Revision ID: a1b2c3d4e5f6
Revises: 52c0db8cab28
Create Date: 2026-02-19 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '52c0db8cab28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # git_providers
    op.create_table('git_providers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('provider_type', sa.Enum('GITHUB', 'GITLAB', name='providertype'), nullable=False),
        sa.Column('base_url', sa.String(length=500), nullable=True),
        sa.Column('token', sa.String(length=500), nullable=False),
        sa.Column('org_name', sa.String(length=200), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # repositories
    op.create_table('repositories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('git_provider_id', sa.Integer(), nullable=False),
        sa.Column('repo_name', sa.String(length=200), nullable=False),
        sa.Column('repo_full_name', sa.String(length=500), nullable=False),
        sa.Column('repo_url', sa.String(length=500), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['git_provider_id'], ['git_providers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # recipients
    op.create_table('recipients',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('email', sa.String(length=300), nullable=False),
        sa.Column('report_types', sa.String(length=100), nullable=False, server_default='all'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.UniqueConstraint('email'),
        sa.PrimaryKeyConstraint('id')
    )

    # app_settings
    op.create_table('app_settings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.String(length=1000), nullable=False),
        sa.Column('value_type', sa.String(length=20), nullable=False, server_default='string'),
        sa.Column('category', sa.String(length=50), nullable=False, server_default='general'),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.UniqueConstraint('key'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_table('recipients')
    op.drop_table('repositories')
    op.drop_table('git_providers')
