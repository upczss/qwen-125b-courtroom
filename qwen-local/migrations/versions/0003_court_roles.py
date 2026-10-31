from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

def upgrade():
    # Rename ownership role; never guess which side an existing discussant represents.
    op.execute("UPDATE court_members SET role='judge' WHERE role='creator'")
    op.execute("UPDATE court_members SET role='pending' WHERE role='discussant'")
    op.execute("UPDATE court_messages SET role='judge' WHERE role='creator'")

def downgrade():
    op.execute("UPDATE court_members SET role='creator' WHERE role='judge'")
    op.execute("UPDATE court_members SET role='discussant' WHERE role IN ('pending','plaintiff','defendant')")
    op.execute("UPDATE court_messages SET role='creator' WHERE role='judge'")
