"""
CRM database client for the Kapruka Gift Agent.

This client handles only the lightweight CRM layer for the project.
The reusable memory system remains separate:
- st_turns stores short-term conversation turns
- mem_facts stores semantic user preference facts
- mem_episodes stores summarized past conversations
- mem_procedures stores reusable agent workflows

The Kapruka product catalog is not stored here. Product metadata is
vectorized and stored in Qdrant for RAG retrieval.
"""

import time
from loguru import logger
from typing import Dict, List, Optional, Any

from infrastructure.db import get_sql_engine
from infrastructure.db.crm_models import User


class CRMDatabaseClient:
    """
    CRM client backed by Supabase PostgreSQL.

    For the Kapruka mini project, the CRM database only stores the core
    application user profile. Preferences such as "user loves dark chocolate"
    should be stored in mem_facts, not directly in the users table.
    """

    def __init__(self):
        """Initialize CRM database client."""
        self.engine = get_sql_engine()

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """
        Get a user profile by internal CRM user_id.

        Args:
            user_id: Internal CRM user identifier

        Returns:
            User profile dictionary or None if not found
        """
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=self.engine)
        session = Session()

        try:
            user = (
                session.query(User)
                .filter(User.user_id == user_id)
                .first()
            )

            return user.to_dict() if user else None

        except Exception as e:
            logger.error(f"Failed to get user by user_id={user_id}: {e}")
            return None

        finally:
            session.close()

    def get_user_by_external_id(self, external_user_id: str) -> Optional[Dict]:
        """
        Get a user profile by external user ID.

        The external_user_id should match the application-level user identity,
        such as a frontend auth user ID, phone number, email-based ID, or
        another stable user reference used by the agent.

        Args:
            external_user_id: External application user identifier

        Returns:
            User profile dictionary or None if not found
        """
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=self.engine)
        session = Session()

        try:
            user = (
                session.query(User)
                .filter(User.external_user_id == external_user_id)
                .first()
            )

            return user.to_dict() if user else None

        except Exception as e:
            logger.error(f"Failed to get user by external_user_id={external_user_id}: {e}")
            return None

        finally:
            session.close()

    def create_user(
        self,
        user_id: str,
        external_user_id: str,
        full_name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        district: Optional[str] = None,
        notes: Optional[str] = None,
        active: int = 1,
    ) -> Optional[Dict]:
        """
        Create a new Kapruka CRM user profile.

        This table stores stable profile/contact data only. Preference facts,
        allergies, likes, dislikes, budget preferences, and gift behavior
        should be saved in mem_facts.

        Args:
            user_id: Internal CRM user identifier
            external_user_id: External application user identifier
            full_name: User's full name
            phone: Optional phone number
            email: Optional email address
            district: Optional Sri Lankan delivery district
            notes: Optional CRM notes
            active: 1 for active user, 0 for inactive user

        Returns:
            Created user profile dictionary or None on failure
        """
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=self.engine)
        session = Session()

        try:
            now = int(time.time())

            existing = (
                session.query(User)
                .filter(User.external_user_id == external_user_id)
                .first()
            )

            if existing:
                logger.info(f"User already exists for external_user_id={external_user_id}")
                return existing.to_dict()

            user = User(
                user_id=user_id,
                external_user_id=external_user_id,
                full_name=full_name,
                phone=phone,
                email=email,
                district=district,
                notes=notes,
                active=active,
                created_at=now,
                updated_at=now,
            )

            session.add(user)
            session.commit()
            session.refresh(user)

            logger.info(f"Created Kapruka CRM user {user_id}")
            return user.to_dict()

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to create user: {e}")
            return None

        finally:
            session.close()

    def update_user_profile(
        self,
        external_user_id: str,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        district: Optional[str] = None,
        notes: Optional[str] = None,
        active: Optional[int] = None,
    ) -> Optional[Dict]:
        """
        Update basic CRM profile fields for a Kapruka user.

        Do not use this method to store preference facts. For example:
        - "User loves dark chocolate" goes to mem_facts
        - "User is allergic to nuts" goes to mem_facts
        - "User lives in Kandy" may be stored here as district and also
          optionally remembered as a semantic fact

        Args:
            external_user_id: External application user identifier
            full_name: Optional updated full name
            phone: Optional updated phone number
            email: Optional updated email address
            district: Optional updated delivery district
            notes: Optional updated CRM notes
            active: Optional active flag

        Returns:
            Updated user profile dictionary or None if not found/failure
        """
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=self.engine)
        session = Session()

        try:
            user = (
                session.query(User)
                .filter(User.external_user_id == external_user_id)
                .first()
            )

            if not user:
                logger.warning(f"No user found for external_user_id={external_user_id}")
                return None

            if full_name is not None:
                user.full_name = full_name
            if phone is not None:
                user.phone = phone
            if email is not None:
                user.email = email
            if district is not None:
                user.district = district
            if notes is not None:
                user.notes = notes
            if active is not None:
                user.active = active

            user.updated_at = int(time.time())

            session.commit()
            session.refresh(user)

            logger.info(f"Updated Kapruka CRM user external_user_id={external_user_id}")
            return user.to_dict()

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to update user profile: {e}")
            return None

        finally:
            session.close()

    def upsert_user_profile(
        self,
        user_id: str,
        external_user_id: str,
        full_name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        district: Optional[str] = None,
        notes: Optional[str] = None,
        active: int = 1,
    ) -> Optional[Dict]:
        """
        Create or update a Kapruka CRM user profile.

        This is useful when the agent receives profile information during
        signup or conversation and needs to keep the CRM profile current.

        Args:
            user_id: Internal CRM user identifier
            external_user_id: External application user identifier
            full_name: User's full name
            phone: Optional phone number
            email: Optional email address
            district: Optional delivery district
            notes: Optional CRM notes
            active: Active flag

        Returns:
            User profile dictionary or None on failure
        """
        existing = self.get_user_by_external_id(external_user_id)

        if existing:
            return self.update_user_profile(
                external_user_id=external_user_id,
                full_name=full_name,
                phone=phone,
                email=email,
                district=district,
                notes=notes,
                active=active,
            )

        return self.create_user(
            user_id=user_id,
            external_user_id=external_user_id,
            full_name=full_name,
            phone=phone,
            email=email,
            district=district,
            notes=notes,
            active=active,
        )

    def list_users(self, limit: int = 100, active_only: bool = True) -> List[Dict]:
        """
        List Kapruka CRM users.

        Args:
            limit: Maximum number of users to return
            active_only: If True, return only active users

        Returns:
            List of user profile dictionaries
        """
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=self.engine)
        session = Session()

        try:
            query = session.query(User).order_by(User.updated_at.desc())

            if active_only:
                query = query.filter(User.active == 1)

            users = query.limit(limit).all()
            return [user.to_dict() for user in users]

        except Exception as e:
            logger.error(f"Failed to list users: {e}")
            return []

        finally:
            session.close()

    def deactivate_user(self, external_user_id: str) -> bool:
        """
        Soft-disable a Kapruka CRM user profile.

        Args:
            external_user_id: External application user identifier

        Returns:
            True if the user was deactivated, otherwise False
        """
        updated = self.update_user_profile(
            external_user_id=external_user_id,
            active=0,
        )
        return updated is not None


# Singleton instance
_crm_client = None


def get_crm_client() -> CRMDatabaseClient:
    """
    Get singleton CRM database client.

    Returns:
        CRMDatabaseClient instance
    """
    global _crm_client

    if _crm_client is None:
        _crm_client = CRMDatabaseClient()

    return _crm_client
