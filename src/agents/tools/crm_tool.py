"""
CRM Tool — Kapruka user-profile lookup and management.

This CRM layer is intentionally small for the Kapruka Gift Concierge project.

Responsibilities:
  1. lookup_user     — find a user profile by user_id, external_user_id, phone, email, or name
  2. create_user     — create a new user CRM profile
  3. update_user     — update user profile fields such as name, phone, email, district, notes
  4. deactivate_user — mark a user as inactive
  5. list_users      — list recent or active users for debugging/admin use

Important architecture note:
- Product catalog data is NOT managed here. Product metadata is vectorized and stored in Qdrant for RAG retrieval.
- User preferences such as "user likes dark chocolate" are NOT stored directly in this CRM table.
  Those facts belong in mem_facts as semantic memory.
- This CRM table stores stable user identity/profile details only.
"""

from loguru import logger
import uuid
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import sessionmaker

from infrastructure.db import get_sql_engine
from infrastructure.db.crm_models import User
from infrastructure.observability import observe, update_current_observation


class CRMTool:
    """
    CRM tool for the Kapruka routing-engine agent.

    Each public method corresponds to one routable CRM action.
    All methods return human-readable strings for the synthesiser LLM.
    """

    def __init__(self) -> None:
        self.engine = get_sql_engine()

    # ── helpers ────────────────────────────────────────────────

    def _session(self):
        """Create a new SQLAlchemy session."""
        factory = sessionmaker(bind=self.engine)
        return factory()

    @staticmethod
    def _now_epoch() -> int:
        """Return current time as epoch seconds."""
        return int(time.time())

    @staticmethod
    def _format_active(active: Optional[bool]) -> str:
        """Format active flag for display."""
        return "Active" if active is True else "Inactive"

    @staticmethod
    def _safe(value: Optional[str]) -> str:
        """Return display-safe text."""
        return value if value else "N/A"

    # ── 1. lookup_user ────────────────────────────────────────

    def lookup_user(
        self,
        user_id: Optional[str] = None,
        external_user_id: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
    ) -> str:
        """
        Find a Kapruka CRM user profile.

        Search priority:
        user_id → external_user_id → phone → email → name

        Args:
            user_id: Internal CRM user id
            external_user_id: Application/user-channel id
            phone: User phone number
            email: User email
            name: Partial or full user name

        Returns:
            Formatted user details or a not-found message.
        """
        session = self._session()
        try:
            query = session.query(User)

            if user_id:
                query = query.filter(User.user_id == user_id)
            elif external_user_id:
                query = query.filter(User.external_user_id == external_user_id)
            elif phone:
                query = query.filter(User.phone == phone)
            elif email:
                query = query.filter(User.email.ilike(email))
            elif name:
                query = query.filter(User.full_name.ilike(f"%{name}%"))
            else:
                return "No search criteria provided. Please supply user_id, external_user_id, phone, email, or name."

            users = query.limit(5).all()

            if not users:
                return "No user profile found matching the given criteria."

            lines: List[str] = []
            for user in users:
                lines.append(
                    "• "
                    f"{self._safe(user.full_name)}"
                    f" | User ID: {user.user_id}"
                    f" | External ID: {self._safe(user.external_user_id)}"
                    f" | Phone: {self._safe(user.phone)}"
                    f" | Email: {self._safe(user.email)}"
                    f" | District: {self._safe(user.district)}"
                    f" | Status: {self._format_active(user.active)}"
                )

                notes = getattr(user, "notes", None)
                if notes:
                    lines.append(f"  Notes: {notes}")

            return "\n".join(lines)

        except Exception as exc:
            logger.error("lookup_user failed: {}", exc)
            return f"Error looking up user profile: {exc}"
        finally:
            session.close()

    # ── 2. create_user ────────────────────────────────────────

    def create_user(
        self,
        full_name: str,
        external_user_id: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        district: Optional[str] = None,
        notes: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """
        Create a new Kapruka user CRM profile.

        Args:
            full_name: User's full name
            external_user_id: External application/channel identifier
            phone: Contact number
            email: Email address
            district: Sri Lankan district, used by logistics workflows
            notes: Optional CRM notes
            user_id: Optional explicit user id. If omitted, UUID is generated.

        Returns:
            Confirmation or error message.
        """
        session = self._session()
        try:
            if not full_name or not full_name.strip():
                return "Cannot create user profile: full_name is required."

            # Avoid duplicates by external id, phone, or email when provided.
            duplicate_filters = []
            if external_user_id:
                duplicate_filters.append(User.external_user_id == external_user_id)
            if phone:
                duplicate_filters.append(User.phone == phone)
            if email:
                duplicate_filters.append(User.email.ilike(email))

            if duplicate_filters:
                existing = session.query(User).filter(or_(*duplicate_filters)).first()
                if existing:
                    return (
                        "A matching user profile already exists.\n"
                        f"  User ID: {existing.user_id}\n"
                        f"  Name: {self._safe(existing.full_name)}\n"
                        f"  Phone: {self._safe(existing.phone)}\n"
                        f"  Email: {self._safe(existing.email)}"
                    )

            now = self._now_epoch()
            new_user = User(
                user_id=user_id or str(uuid.uuid4()),
                external_user_id=external_user_id,
                full_name=full_name.strip(),
                phone=phone,
                email=email,
                district=district,
                active=True,
                created_at=now,
                updated_at=now,
            )

            if hasattr(new_user, "notes"):
                new_user.notes = notes

            session.add(new_user)
            session.commit()

            return (
                "✅ User profile created.\n"
                f"  User ID: {new_user.user_id}\n"
                f"  Name: {new_user.full_name}\n"
                f"  External ID: {self._safe(new_user.external_user_id)}\n"
                f"  Phone: {self._safe(new_user.phone)}\n"
                f"  Email: {self._safe(new_user.email)}\n"
                f"  District: {self._safe(new_user.district)}"
            )

        except Exception as exc:
            session.rollback()
            logger.error("create_user failed: {}", exc)
            return f"Error creating user profile: {exc}"
        finally:
            session.close()

    # ── 3. update_user ────────────────────────────────────────

    def update_user(
        self,
        user_id: Optional[str] = None,
        external_user_id: Optional[str] = None,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        district: Optional[str] = None,
        notes: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> str:
        """
        Update stable CRM fields for a Kapruka user.

        Do not use this method for preferences such as likes, dislikes, or allergies.
        Preference facts must be extracted and stored in mem_facts.

        Args:
            user_id: Internal CRM user id
            external_user_id: External application/channel id
            full_name: Optional updated name
            phone: Optional updated phone
            email: Optional updated email
            district: Optional updated district
            notes: Optional CRM notes
            active: Optional active flag, True or False

        Returns:
            Updated profile summary or error message.
        """
        session = self._session()
        try:
            if user_id:
                user = session.query(User).filter(User.user_id == user_id).first()
            elif external_user_id:
                user = session.query(User).filter(User.external_user_id == external_user_id).first()
            else:
                return "Cannot update user profile: provide user_id or external_user_id."

            if not user:
                return "User profile not found."

            changed: List[str] = []

            if full_name is not None:
                user.full_name = full_name.strip()
                changed.append("full_name")
            if phone is not None:
                user.phone = phone
                changed.append("phone")
            if email is not None:
                user.email = email
                changed.append("email")
            if district is not None:
                user.district = district
                changed.append("district")
            if active is not None:
                if isinstance(active, int):
                    if active not in (0, 1):
                        return "Invalid active value. Use true or false."
                    active = bool(active)
                elif not isinstance(active, bool):
                    return "Invalid active value. Use true or false."
                user.active = active
                changed.append("active")
            if notes is not None and hasattr(user, "notes"):
                user.notes = notes
                changed.append("notes")

            if not changed:
                return "No update fields provided."

            user.updated_at = self._now_epoch()
            session.commit()

            return (
                "✅ User profile updated.\n"
                f"  User ID: {user.user_id}\n"
                f"  Updated fields: {', '.join(changed)}\n"
                f"  Name: {self._safe(user.full_name)}\n"
                f"  Phone: {self._safe(user.phone)}\n"
                f"  Email: {self._safe(user.email)}\n"
                f"  District: {self._safe(user.district)}\n"
                f"  Status: {self._format_active(user.active)}"
            )

        except Exception as exc:
            session.rollback()
            logger.error("update_user failed: {}", exc)
            return f"Error updating user profile: {exc}"
        finally:
            session.close()

    # ── 4. deactivate_user ────────────────────────────────────

    def deactivate_user(
        self,
        user_id: Optional[str] = None,
        external_user_id: Optional[str] = None,
    ) -> str:
        """
        Mark a user profile as inactive.

        Args:
            user_id: Internal CRM user id
            external_user_id: External application/channel id

        Returns:
            Confirmation or error message.
        """
        return self.update_user(
            user_id=user_id,
            external_user_id=external_user_id,
            active=False,
        )

    # ── 5. list_users ─────────────────────────────────────────

    def list_users(
        self,
        limit: int = 10,
        active_only: bool = True,
        district: Optional[str] = None,
    ) -> str:
        """
        List CRM user profiles for debugging/admin use.

        Args:
            limit: Maximum number of users
            active_only: Whether to return only active users
            district: Optional district filter

        Returns:
            Formatted user list.
        """
        session = self._session()
        try:
            query = session.query(User)

            if active_only:
                query = query.filter(User.active.is_(True))
            if district:
                query = query.filter(User.district.ilike(f"%{district}%"))

            users = query.order_by(User.created_at.desc()).limit(limit).all()

            if not users:
                return "No user profiles found."

            lines = ["Kapruka CRM user profiles:"]
            for user in users:
                lines.append(
                    "• "
                    f"{self._safe(user.full_name)}"
                    f" | User ID: {user.user_id}"
                    f" | External ID: {self._safe(user.external_user_id)}"
                    f" | District: {self._safe(user.district)}"
                    f" | Phone: {self._safe(user.phone)}"
                    f" | Status: {self._format_active(user.active)}"
                )

            return "\n".join(lines)

        except Exception as exc:
            logger.error("list_users failed: {}", exc)
            return f"Error listing user profiles: {exc}"
        finally:
            session.close()

    # ── dispatch ──────────────────────────────────────────────

    @observe(name="crm_dispatch")
    def dispatch(self, action: str, params: Dict[str, Any]) -> str:
        """
        Dispatch a CRM action by name.

        Traced via LangFuse so each CRM call is visible with its
        action type, parameters, and latency.
        """
        handler_map = {
            "lookup_user": self.lookup_user,
            "create_user": self.create_user,
            "update_user": self.update_user,
            "deactivate_user": self.deactivate_user,
            "list_users": self.list_users,
        }
        handler = handler_map.get(action)
        if not handler:
            return f"Unknown CRM action: {action}. Available: {list(handler_map.keys())}"

        update_current_observation(
            input=f"action={action} params={params}",
        )

        start = time.time()
        result = handler(**params)
        latency_ms = int((time.time() - start) * 1000)

        update_current_observation(
            output=result[:500],
            metadata={"action": action, "latency_ms": latency_ms},
        )

        return result
