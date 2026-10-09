"""Scope-bound non-executable output templates; no business facts are rewritten."""
from alembic import op
import sqlalchemy as sa

revision = 'v94o01'
down_revision = 'v91s01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('output_templates',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('operational_area_id', sa.Integer(), sa.ForeignKey('operational_areas.id'), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('kind', sa.String(30), nullable=False), sa.Column('name', sa.String(80), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False), sa.Column('configuration', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('case_ledger','material_sections')", name='ck_output_template_kind'))
    op.create_index('ix_output_templates_operational_area_id', 'output_templates', ['operational_area_id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM output_templates LIMIT 1')).first():
        raise RuntimeError('output_templates_require_compatible_backup_before_downgrade')
    op.drop_table('output_templates')
