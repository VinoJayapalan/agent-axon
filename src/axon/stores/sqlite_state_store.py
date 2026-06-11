from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from axon.core.workflow import WorkflowState, WorkflowStatus
from axon.core.events import Event, EventStatus, ArtifactRef


class SQLiteStateStore:
    """SQLite-backed implementation of StateStore."""

    def __init__(self, db_path: str = "data/axon.db") -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                target_agent TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL,
                artifact_refs_json TEXT NOT NULL DEFAULT '[]',
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_stories (
                story_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                acceptance_criteria_json TEXT NOT NULL DEFAULT '[]',
                priority TEXT NOT NULL DEFAULT 'MEDIUM',
                status TEXT NOT NULL DEFAULT 'BACKLOG',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS product_catalog (
                catalog_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                use_cases_json TEXT NOT NULL DEFAULT '[]',
                user_workflows_json TEXT NOT NULL DEFAULT '[]',
                design_decisions_json TEXT NOT NULL DEFAULT '[]',
                components_json TEXT NOT NULL DEFAULT '[]',
                scanned_at TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Workflow                                                              #
    # ------------------------------------------------------------------ #

    def save_workflow(self, state: WorkflowState) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO workflows
                (id, status, current_stage, created_at, updated_at, retry_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                state.workflow_id,
                state.status.value,
                state.current_stage,
                state.created_at.isoformat(),
                state.updated_at.isoformat(),
                state.retry_count,
            ),
        )
        self._conn.commit()

    def get_workflow(self, workflow_id: str) -> WorkflowState | None:
        row = self._conn.execute(
            "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
        if row is None:
            return None
        return WorkflowState(
            workflow_id=row["id"],
            status=WorkflowStatus(row["status"]),
            current_stage=row["current_stage"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            retry_count=row["retry_count"],
        )

    def update_workflow_status(self, workflow_id: str, status: WorkflowStatus) -> None:
        self._conn.execute(
            "UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, datetime.now(timezone.utc).isoformat(), workflow_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Events                                                                #
    # ------------------------------------------------------------------ #

    def save_event(self, event: Event) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO events
                (id, workflow_id, source_agent, target_agent, event_type,
                 status, artifact_refs_json, retry_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.workflow_id,
                event.source_agent,
                event.target_agent,
                event.event_type,
                event.status.value,
                json.dumps([r.model_dump(mode="json") for r in event.artifact_refs]),
                event.retry_count,
                event.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def list_events(self, workflow_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE workflow_id = ? ORDER BY created_at", (workflow_id,)
        ).fetchall()
        events = []
        for row in rows:
            refs = [ArtifactRef(**r) for r in json.loads(row["artifact_refs_json"])]
            events.append(
                Event(
                    event_id=row["id"],
                    workflow_id=row["workflow_id"],
                    source_agent=row["source_agent"],
                    target_agent=row["target_agent"],
                    event_type=row["event_type"],
                    status=EventStatus(row["status"]),
                    artifact_refs=refs,
                    retry_count=row["retry_count"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            )
        return events

    # ------------------------------------------------------------------ #
    # User Stories                                                          #
    # ------------------------------------------------------------------ #

    def save_user_story(
        self,
        workflow_id: str,
        title: str,
        description: str,
        acceptance_criteria: list,
        priority: str,
    ) -> str:
        story_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO user_stories
                (story_id, workflow_id, title, description,
                 acceptance_criteria_json, priority, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'BACKLOG', ?, ?)
            """,
            (story_id, workflow_id, title, description,
             json.dumps(acceptance_criteria), priority, now, now),
        )
        self._conn.commit()
        return story_id

    def update_user_story_status(self, story_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE user_stories SET status = ?, updated_at = ? WHERE story_id = ?",
            (status, datetime.now(timezone.utc).isoformat(), story_id),
        )
        self._conn.commit()

    def list_user_stories(self, workflow_id: str | None = None) -> list[dict]:
        if workflow_id:
            rows = self._conn.execute(
                "SELECT * FROM user_stories WHERE workflow_id = ?", (workflow_id,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM user_stories").fetchall()
        return [dict(row) for row in rows]

    def find_similar_story(self, title: str) -> dict | None:
        title_lower = title.lower()
        rows = self._conn.execute(
            "SELECT * FROM user_stories WHERE status != 'REJECTED'"
        ).fetchall()
        for row in rows:
            if title_lower in row["title"].lower() or row["title"].lower() in title_lower:
                return dict(row)
        return None

    # ------------------------------------------------------------------ #
    # Product Catalog                                                        #
    # ------------------------------------------------------------------ #

    def save_product_catalog(
        self,
        workflow_id: str,
        use_cases: list,
        user_workflows: list,
        design_decisions: list,
        components: list,
    ) -> None:
        catalog_id = str(uuid.uuid4())
        self._conn.execute(
            """
            INSERT INTO product_catalog
                (catalog_id, workflow_id, use_cases_json, user_workflows_json,
                 design_decisions_json, components_json, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                catalog_id, workflow_id,
                json.dumps(use_cases), json.dumps(user_workflows),
                json.dumps(design_decisions), json.dumps(components),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def get_latest_product_catalog(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM product_catalog ORDER BY scanned_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return {
            "catalog_id": row["catalog_id"],
            "workflow_id": row["workflow_id"],
            "use_cases": json.loads(row["use_cases_json"]),
            "user_workflows": json.loads(row["user_workflows_json"]),
            "design_decisions": json.loads(row["design_decisions_json"]),
            "components": json.loads(row["components_json"]),
            "scanned_at": row["scanned_at"],
        }
