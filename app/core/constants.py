"""Константы для использования в проекте Meet-Commit."""

# ====== СТАТУСЫ REVIEW QUEUE ======

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_RESOLVED = "resolved"
REVIEW_STATUS_DROPPED = "dropped"

# Для обратной совместимости с существующими статусами в базе
REVIEW_STATUS_CONFIRMED = "confirmed"
REVIEW_STATUS_REJECTED = "rejected"

# ====== НАПРАВЛЕНИЯ КОММИТОВ ======

DIRECTION_MINE = "mine"
DIRECTION_THEIRS = "theirs"

# ====== СТАТУСЫ КОММИТОВ ======

COMMIT_STATUS_OPEN = "open"
COMMIT_STATUS_CLOSED = "closed"
COMMIT_STATUS_IN_PROGRESS = "in_progress"
