"""stage_7b_messaging

Revision ID: e1f2a3b4c5d6
Revises: d9e2f3a4b5c6
Create Date: 2026-11-14 23:55:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd9e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create conversations table
    op.create_table(
        'conversations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('student_id', sa.Uuid(), nullable=False),
        sa.Column('tutor_id', sa.Uuid(), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tutor_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', name='uq_conversations_student_id'),
    )
    op.create_index(op.f('ix_conversations_student_id'), 'conversations', ['student_id'], unique=True)
    op.create_index(op.f('ix_conversations_tutor_id'), 'conversations', ['tutor_id'], unique=False)
    op.create_index(op.f('ix_conversations_last_message_at'), 'conversations', ['last_message_at'], unique=False)

    # 2. Create messages table
    op.create_table(
        'messages',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('conversation_id', sa.Uuid(), nullable=False),
        sa.Column('sender_id', sa.Uuid(), nullable=False),
        sa.Column('content', sa.String(length=5000), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('length(trim(content)) > 0', name='ck_messages_content_not_empty'),
        sa.CheckConstraint('length(content) <= 5000', name='ck_messages_content_max_length'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_messages_sender_id'), 'messages', ['sender_id'], unique=False)
    op.create_index(op.f('ix_messages_is_read'), 'messages', ['is_read'], unique=False)
    op.create_index(op.f('ix_messages_created_at'), 'messages', ['created_at'], unique=False)
    op.create_index('ix_messages_conv_created', 'messages', ['conversation_id', 'created_at'], unique=False)
    op.create_index('ix_messages_conv_is_read', 'messages', ['conversation_id', 'is_read'], unique=False)


def downgrade() -> None:
    # 1. Drop messages table and indexes
    op.drop_index('ix_messages_conv_is_read', table_name='messages')
    op.drop_index('ix_messages_conv_created', table_name='messages')
    op.drop_index(op.f('ix_messages_created_at'), table_name='messages')
    op.drop_index(op.f('ix_messages_is_read'), table_name='messages')
    op.drop_index(op.f('ix_messages_sender_id'), table_name='messages')
    op.drop_index(op.f('ix_messages_conversation_id'), table_name='messages')
    op.drop_table('messages')

    # 2. Drop conversations table and indexes
    op.drop_index(op.f('ix_conversations_last_message_at'), table_name='conversations')
    op.drop_index(op.f('ix_conversations_tutor_id'), table_name='conversations')
    op.drop_index(op.f('ix_conversations_student_id'), table_name='conversations')
    op.drop_table('conversations')
