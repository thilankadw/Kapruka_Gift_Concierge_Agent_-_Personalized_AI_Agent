"""
Unified Kapruka CRM + logistics data seeder.

This script seeds:
- CRM users
- delivery_zones
- delivery_slots
- courier_profiles
- product_delivery_rules
- delivery_history

The reusable memory system is kept separate:
- st_turns stores short-term chat turns
- mem_facts stores semantic user preference facts
- mem_episodes stores summarized past interactions
- mem_procedures stores reusable agent workflows

The Kapruka product catalog is not seeded here because product metadata is
vectorized and stored in Qdrant for RAG retrieval.
"""

import argparse
import json
import random
import sys
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from infrastructure.log import setup_logging
from infrastructure.observability import flush, observe


class DataGenerationMode(Enum):
    """Data generation mode for user records."""

    LLM = "llm"
    TEMPLATE = "template"


class StorageBackend(Enum):
    """Storage backend for CRM seed data."""

    DATABASE = "database"
    JSONL = "jsonl"


@dataclass
class CRMSeederConfig:
    """Configuration for the Kapruka CRM/logistics seeder."""

    generation_mode: DataGenerationMode = DataGenerationMode.LLM
    storage_backend: StorageBackend = StorageBackend.DATABASE
    n_users: int = 20
    timezone: str = "Asia/Colombo"
    rand_seed: int = 42
    output_file: Optional[Path] = None
    logistics_dir: Path = Path("data/logistics")

    def __post_init__(self):
        if self.storage_backend == StorageBackend.JSONL and not self.output_file:
            self.output_file = Path("data/kapruka_users.jsonl")


class DataGenerator:
    """Base class for Kapruka CRM data generators."""

    def generate_users(self, n: int) -> List[Dict]:
        raise NotImplementedError


class StorageAdapter:
    """Base class for storage adapters."""

    def initialize(self):
        raise NotImplementedError

    def store_data(self, data: Dict):
        raise NotImplementedError

    def finalize(self):
        raise NotImplementedError


class LLMDataGenerator(DataGenerator):
    """Generate realistic Sri Lankan user profiles using an LLM."""

    def __init__(self):
        from infrastructure.llm import get_chat_llm
        from infrastructure.observability import get_langfuse

        get_langfuse()
        self.llm = get_chat_llm()
        self._cache = {}
        self.logger = logger

    @observe(name="seed_generate_kapruka_users", as_type="generation")
    def generate_users(self, n: int) -> List[Dict]:
        cache_key = f"kapruka_users_{n}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        self.logger.info(f"Generating {n} Sri Lankan Kapruka users via LLM...")

        prompt = f"""Generate {n} realistic Sri Lankan user records for a Kapruka gift concierge CRM.

Requirements:
- Mix of Sinhala and Tamil names
- Mix of male and female users
- Adults only
- Use realistic Sri Lankan districts
- Do not include preferences, allergies, gift history, or product data
- Preferences will be stored separately in semantic memory facts

Output as JSON array only:
[
  {{
    "full_name": "Anushka Perera",
    "gender": "F",
    "district": "Colombo",
    "phone": "+94771234567",
    "email": "anushka.perera@gmail.com"
  }}
]

Generate exactly {n} users:"""

        try:
            response = self.llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            json_start = content.find("[")
            json_end = content.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                users = json.loads(content[json_start:json_end])
            else:
                raise ValueError("No JSON array found in LLM response")

            users = users[:n]
            self._cache[cache_key] = users
            self.logger.info(f"Generated {len(users)} Kapruka users")
            return users
        except Exception as exc:
            self.logger.error(f"LLM user generation failed: {exc}")
            self.logger.warning("Falling back to template users...")
            return TemplateDataGenerator().generate_users(n)


class TemplateDataGenerator(DataGenerator):
    """Generate deterministic Kapruka CRM users using templates."""

    DISTRICTS = [
        "Colombo",
        "Gampaha",
        "Kalutara",
        "Kandy",
        "Galle",
        "Matara",
        "Kurunegala",
        "Jaffna",
        "Anuradhapura",
        "Badulla",
        "Ratnapura",
        "Trincomalee",
        "Batticaloa",
        "Nuwara Eliya",
        "Hambantota",
    ]

    BASE_USERS = [
        ("Anushka Perera", "F"),
        ("Kamal Jayasuriya", "M"),
        ("Nethmi Wijesinghe", "F"),
        ("Sunil Fernando", "M"),
        ("Madhavi Silva", "F"),
        ("Arjun Sivarajah", "M"),
        ("Tharushi Gunawardena", "F"),
        ("Dinesh Wickramasinghe", "M"),
        ("Kavindi Rajapaksha", "F"),
        ("Pradeep Bandara", "M"),
        ("Yalini Thevarajah", "F"),
        ("Roshan De Silva", "M"),
    ]

    def __init__(self):
        self.logger = logger

    def generate_users(self, n: int) -> List[Dict]:
        users = []
        for i in range(n):
            name, gender = self.BASE_USERS[i % len(self.BASE_USERS)]
            district = self.DISTRICTS[i % len(self.DISTRICTS)]
            unique_suffix = i + 1

            full_name = f"{name} {unique_suffix}" if i >= len(self.BASE_USERS) else name
            name_parts = full_name.lower().replace(".", "").split()
            email = f"{name_parts[0]}.{name_parts[-1]}{unique_suffix}@gmail.com"
            phone = f"+947{random.randint(10000000, 99999999)}"

            users.append(
                {
                    "full_name": full_name,
                    "gender": gender,
                    "district": district,
                    "phone": phone,
                    "email": email,
                }
            )

        self.logger.info(f"Generated {len(users)} Kapruka users from templates")
        return users


class DatabaseStorageAdapter(StorageAdapter):
    """Store Kapruka CRM data in Supabase/PostgreSQL or local SQL database."""

    CLEAR_ORDER = [
        "delivery_history",
        "delivery_slots",
        "courier_profiles",
        "product_delivery_rules",
        "delivery_zones",
        "users",
    ]

    def __init__(self, config: CRMSeederConfig):
        self.config = config
        self.logger = logger

        from infrastructure.db.crm_models import (
            CourierProfile,
            DeliveryHistory,
            DeliverySlot,
            DeliveryZone,
            ProductDeliveryRule,
            User,
        )
        from infrastructure.db.sql_client import get_sql_engine

        self.engine = get_sql_engine()
        self.Session = sessionmaker(bind=self.engine)
        self.models = {
            "User": User,
            "DeliveryZone": DeliveryZone,
            "DeliverySlot": DeliverySlot,
            "CourierProfile": CourierProfile,
            "ProductDeliveryRule": ProductDeliveryRule,
            "DeliveryHistory": DeliveryHistory,
        }
        self.session = None

    def initialize(self):
        from infrastructure.db.crm_init import ensure_crm_schema_compatibility
        from infrastructure.db.supabase_client import init_supabase_schema

        init_supabase_schema()
        ensure_crm_schema_compatibility()
        self.logger.info("Kapruka CRM/logistics schema ready")

        self.session = self.Session()
        if "sqlite" in str(self.engine.url):
            self.session.execute(text("PRAGMA foreign_keys = ON"))

        self._clear_existing_data()
        self.logger.info("Database initialized for Kapruka CRM/logistics seeding")

    def _clear_existing_data(self):
        inspector = inspect(self.engine)
        existing_tables = set(
            inspector.get_table_names(schema="public")
            if "postgresql" in str(self.engine.url)
            else inspector.get_table_names()
        )

        for table_name in self.CLEAR_ORDER:
            if table_name not in existing_tables:
                self.logger.info(f"Skipping clear for missing table: {table_name}")
                continue
            self.session.execute(text(f"DELETE FROM {table_name}"))

        self.session.commit()
        self.logger.info("Cleared existing Kapruka CRM/logistics seed data")

    def store_data(self, data: Dict):
        model_class = self.models[data["type"]]
        instance = model_class(**data["data"])
        self.session.add(instance)

    def finalize(self):
        if self.session is not None:
            self.session.commit()
            self.session.close()
            self.session = None
        self.logger.info("Kapruka CRM/logistics data committed to database")


class JSONLStorageAdapter(StorageAdapter):
    """Store Kapruka CRM users in a JSONL file."""

    def __init__(self, config: CRMSeederConfig):
        self.config = config
        self.logger = logger
        self.users = []

    def initialize(self):
        self.config.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"JSONL output file: {self.config.output_file}")

    def store_data(self, data: Dict):
        if data["type"] == "User":
            self.users.append(data["data"])

    def finalize(self):
        with open(self.config.output_file, "w", encoding="utf-8") as file:
            for user in self.users:
                file.write(json.dumps(user, ensure_ascii=False) + "\n")
        self.logger.info(f"Wrote {len(self.users)} users to {self.config.output_file}")


class UnifiedCRMSeeder:
    """Unified Kapruka CRM/logistics seeder."""

    USER_SQL_SEED_FILE = "sql/01_users.sql"
    LOGISTICS_JSON_SOURCES = [
        ("DeliveryZone", "delivery_zones.json"),
        ("DeliverySlot", "delivery_slots.json"),
        ("CourierProfile", "courier_profiles.json"),
        ("ProductDeliveryRule", "product_delivery_rules.json"),
        ("DeliveryHistory", "delivery_history.json"),
    ]

    def __init__(self, config: CRMSeederConfig):
        self.config = config
        self.logger = logger
        self.project_root = Path(__file__).parent.parent
        self.generator = self._create_generator()
        self.storage = self._create_storage()
        random.seed(config.rand_seed)

    def _create_generator(self) -> DataGenerator:
        if self.config.generation_mode == DataGenerationMode.LLM:
            self.logger.info("Using LLM user generator")
            return LLMDataGenerator()
        self.logger.info("Using template user generator")
        return TemplateDataGenerator()

    def _create_storage(self) -> StorageAdapter:
        if self.config.storage_backend == StorageBackend.DATABASE:
            self.logger.info("Using database storage")
            return DatabaseStorageAdapter(self.config)
        self.logger.info("Using JSONL storage")
        return JSONLStorageAdapter(self.config)

    def _user_sql_seed_exists(self) -> bool:
        return (self.project_root / self.USER_SQL_SEED_FILE).exists()

    def _load_json_source(self, filename: str) -> List[Dict]:
        path = self.project_root / self.config.logistics_dir / filename
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _seed_logistics_from_json(self) -> Dict[str, int]:
        if self.config.storage_backend != StorageBackend.DATABASE:
            self.logger.info("Skipping logistics table seeding in JSONL mode")
            return {}

        counts: Dict[str, int] = {}
        self.logger.info("Loading logistics reference data from JSON sources")

        for record_type, filename in self.LOGISTICS_JSON_SOURCES:
            rows = self._load_json_source(filename)
            counts[record_type] = len(rows)
            for row in rows:
                self.storage.store_data({"type": record_type, "data": row})
            if (
                self.config.storage_backend == StorageBackend.DATABASE
                and isinstance(self.storage, DatabaseStorageAdapter)
                and self.storage.session is not None
            ):
                self.storage.session.flush()

        self.logger.info(
            "Loaded logistics rows from JSON: {}",
            {key: value for key, value in counts.items()},
        )
        return counts

    def _seed_users_from_sql(self) -> int:
        from infrastructure.db.sql_client import get_sql_engine

        engine = get_sql_engine()
        sql_path = self.project_root / self.USER_SQL_SEED_FILE
        sql_content = sql_path.read_text(encoding="utf-8")

        self.logger.info("Found SQL user seed file, loading deterministic users")

        try:
            with engine.begin() as conn:
                lines = [
                    line for line in sql_content.splitlines()
                    if line.strip() and not line.strip().startswith("--")
                ]
                statements = [
                    stmt.strip() for stmt in "\n".join(lines).split(";") if stmt.strip()
                ]
                for stmt in statements:
                    conn.execute(text(stmt))

                user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0

            self.logger.info(f"Loaded {user_count} users from {self.USER_SQL_SEED_FILE}")
            return int(user_count)
        except Exception as exc:
            self.logger.error(f"SQL user seed failed: {exc}")
            self.logger.info("Falling back to generated users...")
            return 0

    def seed(self):
        self.logger.info("=" * 70)
        self.logger.info("Starting Kapruka CRM + logistics seeding")
        self.logger.info("=" * 70)

        start_time = time.time()
        self.storage.initialize()

        logistics_counts = self._seed_logistics_from_json()
        users: List[Dict] = []
        user_count = 0

        if (
            self.config.storage_backend == StorageBackend.DATABASE
            and self._user_sql_seed_exists()
        ):
            # Commit JSON-backed logistics rows before using the raw SQL user seed.
            self.storage.finalize()
            user_count = self._seed_users_from_sql()
            if user_count == 0 and isinstance(self.storage, DatabaseStorageAdapter):
                self.storage.session = self.storage.Session()
                if "sqlite" in str(self.storage.engine.url):
                    self.storage.session.execute(text("PRAGMA foreign_keys = ON"))
                users = self._seed_users()
                user_count = len(users)
                self.storage.finalize()
        else:
            users = self._seed_users()
            user_count = len(users)
            self.storage.finalize()

        elapsed = time.time() - start_time
        self.logger.info("=" * 70)
        self.logger.info("Kapruka CRM + logistics seeding complete")
        self.logger.info(f"Time: {elapsed:.1f}s")
        self.logger.info(f"Users: {user_count}")
        if logistics_counts:
            self.logger.info(f"Delivery zones: {logistics_counts.get('DeliveryZone', 0)}")
            self.logger.info(f"Delivery slots: {logistics_counts.get('DeliverySlot', 0)}")
            self.logger.info(f"Courier profiles: {logistics_counts.get('CourierProfile', 0)}")
            self.logger.info(
                f"Product delivery rules: {logistics_counts.get('ProductDeliveryRule', 0)}"
            )
            self.logger.info(
                f"Delivery history rows: {logistics_counts.get('DeliveryHistory', 0)}"
            )
        self.logger.info("Product catalog: not seeded here, stored in Qdrant")
        self.logger.info("Preferences: extracted later into mem_facts")
        self.logger.info("=" * 70)

    def _seed_users(self) -> List[Dict]:
        self.logger.info(f"Seeding {self.config.n_users} Kapruka users...")

        users_data = self.generator.generate_users(self.config.n_users)
        users = []

        for user_data in users_data:
            user_id = str(uuid.uuid4())
            phone = user_data.get("phone") or f"+947{random.randint(10000000, 99999999)}"
            external_user_id = phone.replace("+", "")

            full_name = user_data.get("full_name", "Kapruka User")
            email = user_data.get("email")
            if not email:
                name_parts = full_name.lower().replace(".", "").split()
                if len(name_parts) > 1:
                    email = f"{name_parts[0]}.{name_parts[-1]}@gmail.com"
                else:
                    email = f"{name_parts[0]}@gmail.com"

            now = int(time.time())
            data = {
                "type": "User",
                "data": {
                    "user_id": user_id,
                    "external_user_id": external_user_id,
                    "full_name": full_name,
                    "phone": phone,
                    "email": email,
                    "district": user_data.get("district"),
                    "province": user_data.get("province"),
                    "address": user_data.get("address"),
                    "notes": user_data.get("notes"),
                    "active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            }

            self.storage.store_data(data)
            users.append({"id": user_id, **data["data"]})

        return users


def main():
    parser = argparse.ArgumentParser(
        description="Unified Kapruka CRM + logistics data seeder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python seed_crm_unified.py --n-users 20
  python seed_crm_unified.py --mode template --n-users 50
  python seed_crm_unified.py --mode template --storage jsonl --output data/kapruka_users.jsonl
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["llm", "template"],
        default="llm",
        help="User data generation mode",
    )
    parser.add_argument(
        "--storage",
        choices=["database", "jsonl"],
        default="database",
        help="Storage backend",
    )
    parser.add_argument("--n-users", type=int, default=20, help="Number of CRM users")
    parser.add_argument("--tz", default="Asia/Colombo", help="Timezone")
    parser.add_argument("--output", type=Path, help="Output file for JSONL mode")
    parser.add_argument("--rand-seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()

    setup_logging()

    config = CRMSeederConfig(
        generation_mode=DataGenerationMode(args.mode),
        storage_backend=StorageBackend(args.storage),
        n_users=args.n_users,
        timezone=args.tz,
        rand_seed=args.rand_seed,
        output_file=args.output,
    )

    seeder = UnifiedCRMSeeder(config)
    seeder.seed()

    flush()


if __name__ == "__main__":
    main()
