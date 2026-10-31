from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('court_rooms',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('invite_code', sa.String(16), unique=True, nullable=False),
        sa.Column('creator_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('phase', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('court_members',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('room_id', sa.Integer(), sa.ForeignKey('court_rooms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.UniqueConstraint('room_id', 'user_id'))
    op.create_index('ix_court_members_room_id', 'court_members', ['room_id'])
    op.create_table('court_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('room_id', sa.Integer(), sa.ForeignKey('court_rooms.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('username', sa.String(32), nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_court_messages_room_id', 'court_messages', ['room_id'])

def downgrade():
    op.drop_table('court_messages')
    op.drop_table('court_members')
    op.drop_table('court_rooms')
