"""
CRM database client for the Kapruka Gift Agent.

This client handles:
- CRM user profile records
- Structured logistics reference data

The reusable memory system remains separate:
- st_turns stores short-term conversation turns
- mem_facts stores semantic user preference facts
- mem_episodes stores summarized past conversations
- mem_procedures stores reusable agent workflows

The Kapruka product catalog is not stored here. Product metadata is
vectorized and stored in Qdrant for RAG retrieval.
"""

import time
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import sessionmaker

from infrastructure.db import get_sql_engine
from infrastructure.db.crm_models import (
    CourierProfile,
    DeliveryHistory,
    DeliverySlot,
    DeliveryZone,
    ProductDeliveryRule,
    User,
)


class CRMDatabaseClient:
    """
    CRM client backed by Supabase PostgreSQL.

    This project uses the SQL database for:
    - stable customer profile data
    - structured logistics reference data

    Preference facts such as "user loves dark chocolate" should still be stored
    in mem_facts, not directly in the CRM users table.
    """

    def __init__(self):
        self.engine = get_sql_engine()
        self.Session = sessionmaker(bind=self.engine)

    def _session(self):
        return self.Session()

    # ---------------------------------------------------------------------
    # User profile methods
    # ---------------------------------------------------------------------

    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        session = self._session()
        try:
            user = session.query(User).filter(User.user_id == user_id).first()
            return user.to_dict() if user else None
        except Exception as exc:
            logger.error(f"Failed to get user by user_id={user_id}: {exc}")
            return None
        finally:
            session.close()

    def get_user_by_external_id(self, external_user_id: str) -> Optional[Dict]:
        session = self._session()
        try:
            user = (
                session.query(User)
                .filter(User.external_user_id == external_user_id)
                .first()
            )
            return user.to_dict() if user else None
        except Exception as exc:
            logger.error(
                f"Failed to get user by external_user_id={external_user_id}: {exc}"
            )
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
        province: Optional[str] = None,
        address: Optional[str] = None,
        notes: Optional[str] = None,
        active: bool = True,
    ) -> Optional[Dict]:
        session = self._session()
        try:
            now = int(time.time())

            existing = (
                session.query(User)
                .filter(User.external_user_id == external_user_id)
                .first()
            )
            if existing:
                logger.info(
                    f"User already exists for external_user_id={external_user_id}"
                )
                return existing.to_dict()

            user = User(
                user_id=user_id,
                external_user_id=external_user_id,
                full_name=full_name,
                phone=phone,
                email=email,
                district=district,
                province=province,
                address=address,
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
        except Exception as exc:
            session.rollback()
            logger.error(f"Failed to create user: {exc}")
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
        province: Optional[str] = None,
        address: Optional[str] = None,
        notes: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> Optional[Dict]:
        session = self._session()
        try:
            user = (
                session.query(User)
                .filter(User.external_user_id == external_user_id)
                .first()
            )

            if not user:
                logger.warning(
                    f"No user found for external_user_id={external_user_id}"
                )
                return None

            if full_name is not None:
                user.full_name = full_name
            if phone is not None:
                user.phone = phone
            if email is not None:
                user.email = email
            if district is not None:
                user.district = district
            if province is not None:
                user.province = province
            if address is not None:
                user.address = address
            if notes is not None:
                user.notes = notes
            if active is not None:
                user.active = active

            user.updated_at = int(time.time())

            session.commit()
            session.refresh(user)

            logger.info(
                f"Updated Kapruka CRM user external_user_id={external_user_id}"
            )
            return user.to_dict()
        except Exception as exc:
            session.rollback()
            logger.error(f"Failed to update user profile: {exc}")
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
        province: Optional[str] = None,
        address: Optional[str] = None,
        notes: Optional[str] = None,
        active: bool = True,
    ) -> Optional[Dict]:
        existing = self.get_user_by_external_id(external_user_id)
        if existing:
            return self.update_user_profile(
                external_user_id=external_user_id,
                full_name=full_name,
                phone=phone,
                email=email,
                district=district,
                province=province,
                address=address,
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
            province=province,
            address=address,
            notes=notes,
            active=active,
        )

    def list_users(self, limit: int = 100, active_only: bool = True) -> List[Dict]:
        session = self._session()
        try:
            query = session.query(User).order_by(User.updated_at.desc())
            if active_only:
                query = query.filter(User.active.is_(True))
            users = query.limit(limit).all()
            return [user.to_dict() for user in users]
        except Exception as exc:
            logger.error(f"Failed to list users: {exc}")
            return []
        finally:
            session.close()

    def deactivate_user(self, external_user_id: str) -> bool:
        updated = self.update_user_profile(
            external_user_id=external_user_id,
            active=False,
        )
        return updated is not None

    # ---------------------------------------------------------------------
    # Logistics methods
    # ---------------------------------------------------------------------

    def get_delivery_zone(self, district: str) -> Optional[Dict]:
        session = self._session()
        try:
            zone = (
                session.query(DeliveryZone)
                .filter(DeliveryZone.district.ilike(district))
                .first()
            )
            return zone.to_dict() if zone else None
        except Exception as exc:
            logger.error(f"Failed to get delivery zone for district={district}: {exc}")
            return None
        finally:
            session.close()

    def list_delivery_slots(
        self,
        district: str,
        available_only: bool = False,
    ) -> List[Dict]:
        session = self._session()
        try:
            query = (
                session.query(DeliverySlot)
                .filter(DeliverySlot.district.ilike(district))
                .order_by(DeliverySlot.slot.asc())
            )
            if available_only:
                query = query.filter(DeliverySlot.available.is_(True))
            return [slot.to_dict() for slot in query.all()]
        except Exception as exc:
            logger.error(f"Failed to list delivery slots for district={district}: {exc}")
            return []
        finally:
            session.close()

    def list_couriers(
        self,
        district: Optional[str] = None,
        vehicle_type: Optional[str] = None,
        available_only: bool = True,
        limit: int = 20,
    ) -> List[Dict]:
        session = self._session()
        try:
            query = session.query(CourierProfile).order_by(
                CourierProfile.rating.desc(),
                CourierProfile.name.asc(),
            )
            if district:
                query = query.filter(CourierProfile.district.ilike(district))
            if vehicle_type:
                query = query.filter(CourierProfile.vehicle_type.ilike(vehicle_type))
            if available_only:
                query = query.filter(CourierProfile.availability.is_(True))
            return [courier.to_dict() for courier in query.limit(limit).all()]
        except Exception as exc:
            logger.error(f"Failed to list couriers: {exc}")
            return []
        finally:
            session.close()

    def get_product_delivery_rule(self, product_type: str) -> Optional[Dict]:
        session = self._session()
        try:
            rule = (
                session.query(ProductDeliveryRule)
                .filter(ProductDeliveryRule.product_type.ilike(product_type))
                .first()
            )
            return rule.to_dict() if rule else None
        except Exception as exc:
            logger.error(
                f"Failed to get product delivery rule for product_type={product_type}: {exc}"
            )
            return None
        finally:
            session.close()

    def list_delivery_history(
        self,
        district: Optional[str] = None,
        product_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        session = self._session()
        try:
            query = session.query(DeliveryHistory).order_by(DeliveryHistory.order_id.desc())
            if district:
                query = query.filter(DeliveryHistory.district.ilike(district))
            if product_type:
                query = query.filter(DeliveryHistory.product_type.ilike(product_type))
            if status:
                query = query.filter(DeliveryHistory.status.ilike(status))
            return [row.to_dict() for row in query.limit(limit).all()]
        except Exception as exc:
            logger.error(f"Failed to list delivery history: {exc}")
            return []
        finally:
            session.close()

    def check_delivery_options(
        self,
        district: str,
        product_type: Optional[str] = None,
        slot: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return a combined logistics view for a district and optional product type.
        """
        zone = self.get_delivery_zone(district)
        rule = self.get_product_delivery_rule(product_type) if product_type else None

        slots = self.list_delivery_slots(district=district, available_only=False)
        if slot:
            slots = [item for item in slots if item["slot"] == slot]

        available_slots = [item for item in slots if item["available"]]
        couriers = self.list_couriers(district=district, available_only=True, limit=5)
        history = self.list_delivery_history(
            district=district,
            product_type=product_type,
            limit=100,
        )

        status_counts: Dict[str, int] = {}
        avg_delivery_time: Optional[float] = None
        avg_customer_rating: Optional[float] = None

        if history:
            for item in history:
                status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
            avg_delivery_time = round(
                sum(item["delivery_time_minutes"] for item in history) / len(history),
                2,
            )
            avg_customer_rating = round(
                sum(item["customer_rating"] for item in history) / len(history),
                2,
            )

        return {
            "district": district,
            "product_type": product_type,
            "zone": zone,
            "delivery_slots": slots,
            "available_slots": available_slots,
            "top_available_couriers": couriers,
            "product_delivery_rule": rule,
            "delivery_history_summary": {
                "sample_size": len(history),
                "status_counts": status_counts,
                "avg_delivery_time_minutes": avg_delivery_time,
                "avg_customer_rating": avg_customer_rating,
            },
        }


_crm_client = None


def get_crm_client() -> CRMDatabaseClient:
    """Get singleton CRM database client."""
    global _crm_client
    if _crm_client is None:
        _crm_client = CRMDatabaseClient()
    return _crm_client
