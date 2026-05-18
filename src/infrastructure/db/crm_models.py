"""
CRM database models (SQLAlchemy ORM).

Matches the schema defined in sql/crm_schema.sql.
"""

import time

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base


Base = declarative_base()


class User(Base):
    """
    Kapruka agent user profile.

    This is the CRM profile for the person using the gift-concierge agent.
    Preference facts such as "user loves dark chocolate" or
    "user is allergic to nuts" should be stored in mem_facts,
    not directly inside this table.
    """

    __tablename__ = "users"

    user_id = Column(String, primary_key=True)

    # Optional external identifier from the frontend, auth provider, or chat app.
    # Example: phone number, Supabase auth UID, email username, or session owner id.
    external_user_id = Column(String, unique=True)

    full_name = Column(String)
    phone = Column(String)
    email = Column(String)

    # Basic delivery/profile fields useful for the logistics specialist.
    district = Column(String)
    province = Column(String)
    address = Column(Text)

    # General CRM notes only. Long-term preference facts go to mem_facts.
    notes = Column(Text)

    active = Column(Integer, nullable=False, default=1)
    created_at = Column(Integer, default=lambda: int(time.time()))
    updated_at = Column(
        Integer,
        default=lambda: int(time.time()),
        onupdate=lambda: int(time.time()),
    )

    def to_dict(self):
        """Convert the user profile to a dictionary."""
        return {
            "user_id": self.user_id,
            "external_user_id": self.external_user_id,
            "full_name": self.full_name,
            "phone": self.phone,
            "email": self.email,
            "district": self.district,
            "province": self.province,
            "address": self.address,
            "notes": self.notes,
            "active": self.active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
