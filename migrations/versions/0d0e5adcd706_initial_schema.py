"""initial schema

Revision ID: 0d0e5adcd706
Revises:
Create Date: 2026-04-12 10:31:50.670094

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0d0e5adcd706'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('segments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('distance', sa.Float(), nullable=False),
    sa.Column('elevation_gain', sa.Float(), nullable=True),
    sa.Column('elevation_loss', sa.Float(), nullable=True),
    sa.Column('avg_gradient', sa.Float(), nullable=True),
    sa.Column('elevation_profile', sa.Text(), nullable=True),
    sa.Column('start_lat', sa.Float(), nullable=False),
    sa.Column('start_lon', sa.Float(), nullable=False),
    sa.Column('end_lat', sa.Float(), nullable=False),
    sa.Column('end_lon', sa.Float(), nullable=False),
    sa.Column('reference_line', geoalchemy2.types.Geometry(geometry_type='LINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry'), nullable=False),
    sa.Column('match_tolerance', sa.Float(), server_default='50.0', nullable=True),
    sa.Column('min_match_ratio', sa.Float(), server_default='0.8', nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # geoalchemy2 自动为 Geometry 列创建空间索引，无需手动创建

    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('openid', sa.String(length=64), nullable=False),
    sa.Column('nickname', sa.String(length=64), nullable=True),
    sa.Column('avatar_url', sa.Text(), nullable=True),
    sa.Column('ftp', sa.Integer(), nullable=True),
    sa.Column('weight', sa.Float(), nullable=True),
    sa.Column('bike_type', sa.String(length=20), nullable=True),
    sa.Column('weekly_goal', sa.Float(), server_default='200.0', nullable=True),
    sa.Column('is_admin', sa.Boolean(), server_default='false', nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('openid')
    )

    op.create_table('activities',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=128), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('file_url', sa.Text(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('distance', sa.Float(), nullable=True),
    sa.Column('duration', sa.Integer(), nullable=True),
    sa.Column('elevation_gain', sa.Float(), nullable=True),
    sa.Column('avg_speed', sa.Float(), nullable=True),
    sa.Column('max_speed', sa.Float(), nullable=True),
    sa.Column('avg_power', sa.Float(), nullable=True),
    sa.Column('max_power', sa.Float(), nullable=True),
    sa.Column('avg_hr', sa.Float(), nullable=True),
    sa.Column('max_hr', sa.Float(), nullable=True),
    sa.Column('avg_cadence', sa.Float(), nullable=True),
    sa.Column('calories', sa.Float(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('simplified_track', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('splits', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('power_zones', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_activities_user_started', 'activities', ['user_id', 'started_at'], unique=False)
    op.create_index('idx_activities_user_status', 'activities', ['user_id', 'status'], unique=False)

    op.create_table('segment_efforts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('segment_id', sa.Integer(), nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('elapsed_time', sa.Integer(), nullable=False),
    sa.Column('avg_speed', sa.Float(), nullable=True),
    sa.Column('avg_power', sa.Float(), nullable=True),
    sa.Column('start_index', sa.Integer(), nullable=False),
    sa.Column('end_index', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('segment_id', 'activity_id', name='uq_segment_activity')
    )
    op.create_index('idx_efforts_segment_time', 'segment_efforts', ['segment_id', 'elapsed_time'], unique=False)
    op.create_index('idx_efforts_user', 'segment_efforts', ['user_id'], unique=False)

    op.create_table('trackpoints',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('activity_id', sa.Integer(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('elevation', sa.Float(), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.Column('heart_rate', sa.Integer(), nullable=True),
    sa.Column('cadence', sa.Integer(), nullable=True),
    sa.Column('power', sa.Integer(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT', name='geometry'), nullable=True),
    sa.ForeignKeyConstraint(['activity_id'], ['activities.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_trackpoints_activity', 'trackpoints', ['activity_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_trackpoints_activity', table_name='trackpoints')
    op.drop_table('trackpoints')
    op.drop_index('idx_efforts_user', table_name='segment_efforts')
    op.drop_index('idx_efforts_segment_time', table_name='segment_efforts')
    op.drop_table('segment_efforts')
    op.drop_index('idx_activities_user_status', table_name='activities')
    op.drop_index('idx_activities_user_started', table_name='activities')
    op.drop_table('activities')
    op.drop_table('users')
    op.drop_table('segments')
