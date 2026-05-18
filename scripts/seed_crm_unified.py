"""
Unified Kapruka CRM Data Seeder.

This script seeds only the CRM tables needed by the Kapruka Gift Agent.
The reusable memory system is kept separate:
- st_turns stores short-term chat turns.
- mem_facts stores semantic user preference facts.
- mem_episodes stores summarized past interactions.
- mem_procedures stores reusable agent workflows.

The Kapruka product catalog is not seeded here because product metadata is
vectorized and stored in Qdrant for RAG retrieval.

Features:
- SQL-first seeding if pre-exported SQL files exist.
- Fallback to LLM or template generation when SQL files are absent.
- Switch between database and JSONL storage.
- Configurable user scale and deterministic random seed.
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
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

load_dotenv()

# Add src to path when this file is run from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from infrastructure.log import setup_logging
from infrastructure.observability import observe, flush


# ============================================================================
# CONFIGURATION ENUMS
# ============================================================================

class DataGenerationMode(Enum):
    """Data generation mode."""
    LLM = "llm"
    TEMPLATE = "template"


class StorageBackend(Enum):
    """Storage backend for CRM seed data."""
    DATABASE = "database"
    JSONL = "jsonl"


# ============================================================================
# CONFIGURATION DATACLASS
# ============================================================================

@dataclass
class CRMSeederConfig:
    """Configuration for the Kapruka CRM seeder."""

    generation_mode: DataGenerationMode = DataGenerationMode.LLM
    storage_backend: StorageBackend = StorageBackend.DATABASE

    # CRM scale. For this mini project, CRM only stores users.
    n_users: int = 20

    # Sri Lankan context fields used in the users CRM table.
    timezone: str = "Asia/Colombo"
    rand_seed: int = 42

    # JSONL output if database is not used.
    output_file: Optional[Path] = None

    def __post_init__(self):
        """Validate configuration."""
        if self.storage_backend == StorageBackend.JSONL and not self.output_file:
            self.output_file = Path("data/kapruka_users.jsonl")


# ============================================================================
# BASE CLASSES
# ============================================================================

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


# ============================================================================
# LLM DATA GENERATOR
# ============================================================================

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
        """
        Generate Kapruka gift-agent CRM users.

        These are basic CRM records only. Preferences such as "likes dark
        chocolate" should be extracted later and stored in mem_facts, not here.
        """
        cache_key = f"kapruka_users_{n}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        self.logger.info(f"🤖 Generating {n} Sri Lankan Kapruka users via LLM...")

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
            self.logger.info(f"✓ Generated {len(users)} Kapruka users")
            return users

        except Exception as exc:
            self.logger.error(f"LLM user generation failed: {exc}")
            self.logger.warning("Falling back to template users...")
            return TemplateDataGenerator().generate_users(n)


# ============================================================================
# TEMPLATE DATA GENERATOR
# ============================================================================

class TemplateDataGenerator(DataGenerator):
    """Generate deterministic Kapruka CRM users using templates."""

    DISTRICTS = [
        "Colombo", "Gampaha", "Kalutara", "Kandy", "Galle", "Matara",
        "Kurunegala", "Jaffna", "Anuradhapura", "Badulla", "Ratnapura",
        "Trincomalee", "Batticaloa", "Nuwara Eliya", "Hambantota",
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
        """Generate deterministic user profiles."""
        users = []
        for i in range(n):
            name, gender = self.BASE_USERS[i % len(self.BASE_USERS)]
            district = self.DISTRICTS[i % len(self.DISTRICTS)]
            unique_suffix = i + 1

            if i >= len(self.BASE_USERS):
                full_name = f"{name} {unique_suffix}"
            else:
                full_name = name

            name_parts = full_name.lower().replace(".", "").split()
            email = f"{name_parts[0]}.{name_parts[-1]}{unique_suffix}@gmail.com"
            phone = f"+947{random.randint(10000000, 99999999)}"

            users.append({
                "full_name": full_name,
                "gender": gender,
                "district": district,
                "phone": phone,
                "email": email,
            })

        self.logger.info(f"✓ Generated {len(users)} Kapruka users from templates")
        return users


# ============================================================================
# STORAGE ADAPTERS
# ============================================================================

class DatabaseStorageAdapter(StorageAdapter):
    """Store Kapruka CRM data in Supabase/PostgreSQL or local SQL database."""

    def __init__(self, config: CRMSeederConfig):
        self.config = config
        self.logger = logger

        from infrastructure.db.sql_client import get_sql_engine
        from infrastructure.db.crm_models import User

        self.engine = get_sql_engine()
        self.Session = sessionmaker(bind=self.engine)
        self.models = {"User": User}
        self.session = None

    def initialize(self):
        """Initialize schema and clear existing CRM users."""
        from infrastructure.db.crm_init import init_crm_schema

        init_crm_schema()
        self.logger.info("✓ Kapruka CRM schema ready")

        self.session = self.Session()

        if "sqlite" in str(self.engine.url):
            self.session.execute(text("PRAGMA foreign_keys = ON"))

        self._clear_existing_data()
        self.logger.info("✓ Database initialized for Kapruka CRM")

    def _clear_existing_data(self):
        """Delete existing CRM user seed data."""
        try:
            if "postgresql" in str(self.engine.url):
                result = self.session.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename='users'"
                ))
            else:
                result = self.session.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
                ))

            if result.fetchone() is None:
                self.logger.info("⏭️  users table does not exist yet, skipping clear")
                return

            self.session.execute(text("DELETE FROM users"))
            self.session.commit()
            self.logger.info("✓ Cleared existing Kapruka CRM users")

        except Exception as exc:
            self.session.rollback()
            self.logger.error(f"Failed to clear Kapruka CRM users: {exc}")
            raise

    def store_data(self, data: Dict):
        """Store a user record in the database session."""
        model_class = self.models[data["type"]]
        instance = model_class(**data["data"])
        self.session.add(instance)

    def finalize(self):
        """Commit database changes."""
        self.session.commit()
        self.session.close()
        self.logger.info("✓ Kapruka CRM data committed to database")


class JSONLStorageAdapter(StorageAdapter):
    """Store Kapruka CRM users in a JSONL file."""

    def __init__(self, config: CRMSeederConfig):
        self.config = config
        self.logger = logger
        self.users = []

    def initialize(self):
        """Initialize output file path."""
        self.config.output_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"✓ JSONL output file: {self.config.output_file}")

    def store_data(self, data: Dict):
        """Store user data in memory until finalize."""
        if data["type"] == "User":
            self.users.append(data["data"])

    def finalize(self):
        """Write JSONL file."""
        with open(self.config.output_file, "w", encoding="utf-8") as file:
            for user in self.users:
                file.write(json.dumps(user, ensure_ascii=False) + "\n")

        self.logger.info(f"✓ Wrote {len(self.users)} users to {self.config.output_file}")


# ============================================================================
# UNIFIED KAPRUKA CRM SEEDER
# ============================================================================

class UnifiedCRMSeeder:
    """Unified Kapruka CRM seeder."""

    # Optional deterministic SQL file. Products are intentionally excluded.
    SQL_SEED_FILES = ["sql/01_users.sql"]

    def __init__(self, config: CRMSeederConfig):
        self.config = config
        self.logger = logger
        self.project_root = Path(__file__).parent.parent
        self.generator = self._create_generator()
        self.storage = self._create_storage()
        random.seed(config.rand_seed)

    def _create_generator(self) -> DataGenerator:
        """Create the configured data generator."""
        if self.config.generation_mode == DataGenerationMode.LLM:
            self.logger.info("🤖 Using LLM user generator")
            return LLMDataGenerator()

        self.logger.info("📋 Using template user generator")
        return TemplateDataGenerator()

    def _create_storage(self) -> StorageAdapter:
        """Create the configured storage adapter."""
        if self.config.storage_backend == StorageBackend.DATABASE:
            self.logger.info("🗄️  Using database storage")
            return DatabaseStorageAdapter(self.config)

        self.logger.info("📄 Using JSONL storage")
        return JSONLStorageAdapter(self.config)

    def _sql_files_exist(self) -> bool:
        """Check whether deterministic SQL seed files are available."""
        return all((self.project_root / file).exists() for file in self.SQL_SEED_FILES)

    def _seed_from_sql(self) -> bool:
        """Seed users from pre-exported SQL files."""
        from infrastructure.db.sql_client import get_sql_engine

        engine = get_sql_engine()
        self.logger.info("📂 Found Kapruka SQL seed files, loading deterministic users")

        try:
            with engine.connect() as conn:
                for sql_file in self.SQL_SEED_FILES:
                    path = self.project_root / sql_file
                    sql_content = path.read_text(encoding="utf-8")

                    lines = [
                        line for line in sql_content.splitlines()
                        if line.strip() and not line.strip().startswith("--")
                    ]
                    statements = [
                        stmt.strip() for stmt in "\n".join(lines).split(";")
                        if stmt.strip()
                    ]

                    row_count = 0
                    for stmt in statements:
                        conn.execute(text(stmt))
                        if stmt.upper().startswith("INSERT"):
                            row_count += 1

                    conn.commit()
                    self.logger.info(f"  ✅ users: {row_count} rows loaded from {sql_file}")

            return True

        except Exception as exc:
            self.logger.error(f"❌ Kapruka SQL seed failed: {exc}")
            self.logger.info("   Falling back to generated users...")
            return False

    def seed(self):
        """Run the Kapruka CRM seeding workflow."""
        self.logger.info("=" * 70)
        self.logger.info("🌱 Starting Kapruka CRM user seeding")
        self.logger.info("=" * 70)

        start_time = time.time()

        if self.config.storage_backend == StorageBackend.DATABASE and self._sql_files_exist():
            from infrastructure.db.crm_init import init_crm_schema
            init_crm_schema()

            if self._seed_from_sql():
                elapsed = time.time() - start_time
                self.logger.info("=" * 70)
                self.logger.info(f"✅ Kapruka CRM seeded from SQL in {elapsed:.1f}s")
                self.logger.info("=" * 70)
                return

        self.logger.info("⚙️  No SQL seed files found, generating Kapruka users dynamically")
        self.storage.initialize()

        users = self._seed_users()

        self.storage.finalize()

        elapsed = time.time() - start_time
        self.logger.info("=" * 70)
        self.logger.info("✅ Kapruka CRM seeding complete")
        self.logger.info(f"   Time: {elapsed:.1f}s")
        self.logger.info(f"   Users: {len(users)}")
        self.logger.info("   Product catalog: not seeded here, stored in Qdrant")
        self.logger.info("   Preferences: extracted later into mem_facts")
        self.logger.info("=" * 70)

    def _seed_users(self) -> List[Dict]:
        """Seed users into the CRM users table."""
        self.logger.info(f"👤 Seeding {self.config.n_users} Kapruka users...")

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
                email = f"{name_parts[0]}.{name_parts[-1]}@gmail.com" if len(name_parts) > 1 else f"{name_parts[0]}@gmail.com"

            data = {
                "type": "User",
                "data": {
                    "user_id": user_id,
                    "external_user_id": external_user_id,
                    "full_name": full_name,
                    "gender": user_data.get("gender"),
                    "phone": phone,
                    "email": email,
                    "district": user_data.get("district"),
                    "notes": user_data.get("notes"),
                    "active": 1,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                },
            }

            self.storage.store_data(data)
            users.append({"id": user_id, **data["data"]})

        return users


# ============================================================================
# CLI INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Unified Kapruka CRM Data Seeder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # LLM + database
  python seed_crm_unified.py --n-users 20

  # Template + database
  python seed_crm_unified.py --mode template --n-users 50

  # Template + JSONL file
  python seed_crm_unified.py --mode template --storage jsonl --output data/kapruka_users.jsonl
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["llm", "template"],
        default="llm",
        help="Data generation mode",
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
