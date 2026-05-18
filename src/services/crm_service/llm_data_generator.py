"""
LLM-powered CRM data generator for the Kapruka Gift Concierge project.

This generator creates realistic Sri Lankan user profile seed data for the
minimal CRM database. Product data is not generated here because the Kapruka
product catalog is crawled, vectorized, and stored in Qdrant for RAG retrieval.

User preferences such as "User loves dark chocolate" should be stored in the
memory system, mainly in mem_facts, not in the CRM users table.
"""

import json
from loguru import logger
from typing import List, Dict


class KaprukaDataGenerator:
    """Generate realistic Kapruka CRM seed data using an LLM."""

    def __init__(self, llm):
        """
        Initialize generator with LLM.

        Args:
            llm: Language model instance, usually from get_chat_llm().
        """
        self.llm = llm
        self._cache = {}

    def generate_users(self, n: int) -> List[Dict]:
        """
        Generate Sri Lankan user profile records for the Kapruka CRM.

        The generated records are intended for the users table only.
        Long-term preferences, allergies, likes, dislikes, and gift habits
        should be generated or extracted separately and stored in mem_facts.

        Args:
            n: Number of users to generate.

        Returns:
            List of user dictionaries.
        """
        cache_key = f"users_{n}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        logger.info(f"Generating {n} Sri Lankan Kapruka user profiles via LLM...")

        prompt = f"""Generate {n} realistic Sri Lankan customer profiles for a Kapruka-style online gift concierge CRM.

Requirements:
- Mix of Sinhala, Tamil, and Muslim Sri Lankan names
- Mix of male and female users
- Include realistic Sri Lankan phone numbers
- Include realistic email addresses
- Include Sri Lankan districts, such as Colombo, Gampaha, Kandy, Galle, Matara, Kurunegala, Jaffna, Badulla, Ratnapura, Anuradhapura
- These are CRM identity/profile records only
- Do NOT include product preferences, allergies, gift history, or relationship details
- NO duplicate names or emails

Output as a JSON array:
[
  {{
    "full_name": "Anushka Perera",
    "email": "anushka.perera@example.com",
    "phone": "0771234567",
    "district": "Colombo",
    "notes": "Registered Kapruka gift concierge user"
  }}
]

Generate exactly {n} users:"""

        try:
            response = self.llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            users_data = self._extract_json_array(content)
            users = users_data[:n]

            self._cache[cache_key] = users
            logger.info(f"✓ Generated {len(users)} Kapruka user profiles")
            return users

        except Exception as e:
            logger.error(f"Failed to generate Kapruka users: {e}")
            logger.warning("Falling back to template Kapruka users...")
            return self._fallback_users(n)

    def generate_memory_facts(self, n: int) -> List[Dict]:
        """
        Generate sample semantic memory facts for testing mem_facts.

        These records are not CRM rows. They are examples for the memory layer.
        In the real agent, similar facts should be extracted from user messages
        by the preference update router.

        Args:
            n: Number of memory facts to generate.

        Returns:
            List of fact dictionaries with text, score, and tags.
        """
        cache_key = f"memory_facts_{n}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        logger.info(f"Generating {n} Kapruka semantic memory facts via LLM...")

        prompt = f"""Generate {n} concise semantic memory facts for a Kapruka-style gift recommendation agent.

Requirements:
- Facts should be about the user only
- Include likes, dislikes, allergies, budget preferences, delivery district, and gift style preferences
- Do not mention wife, mother, father, friend, or any relationship
- Each fact must be short and suitable for storage in mem_facts
- Use natural sentences

Output as JSON array:
[
  {{
    "text": "User loves dark chocolate.",
    "score": 0.95,
    "tags": ["preference", "food", "chocolate"]
  }},
  {{
    "text": "User is allergic to nuts.",
    "score": 1.0,
    "tags": ["allergy", "safety"]
  }}
]

Generate exactly {n} facts:"""

        try:
            response = self.llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            facts_data = self._extract_json_array(content)
            facts = facts_data[:n]

            self._cache[cache_key] = facts
            logger.info(f"✓ Generated {len(facts)} semantic memory facts")
            return facts

        except Exception as e:
            logger.error(f"Failed to generate memory facts: {e}")
            logger.warning("Falling back to template memory facts...")
            return self._fallback_memory_facts(n)

    def generate_gift_queries(self, n: int) -> List[str]:
        """
        Generate realistic user queries for testing the router and RAG flow.

        Args:
            n: Number of gift queries to generate.

        Returns:
            List of user query strings.
        """
        cache_key = f"gift_queries_{n}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        logger.info(f"Generating {n} Kapruka gift queries via LLM...")

        prompt = f"""Generate {n} realistic customer messages for a Kapruka gift concierge chatbot.

Requirements:
- Mix product search, preference updates, and delivery questions
- Keep each message short and natural
- Use Sri Lankan context where useful
- Do not include relationship-based recipient wording

Output as a JSON array of strings:
[
  "I love dark chocolate but I cannot eat nuts.",
  "Find a birthday cake under Rs. 5000 for delivery to Kandy.",
  "Can this be delivered to Galle tomorrow?"
]

Generate exactly {n} messages:"""

        try:
            response = self.llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)

            queries = self._extract_json_array(content)[:n]
            self._cache[cache_key] = queries
            logger.info(f"✓ Generated {len(queries)} gift queries")
            return queries

        except Exception as e:
            logger.error(f"Failed to generate gift queries: {e}")
            return self._fallback_gift_queries(n)

    def _extract_json_array(self, content: str):
        """Extract a JSON array from an LLM response."""
        json_start = content.find("[")
        json_end = content.rfind("]") + 1

        if json_start >= 0 and json_end > json_start:
            json_str = content[json_start:json_end]
            return json.loads(json_str)

        raise ValueError("No JSON array found in response")

    def _fallback_users(self, n: int) -> List[Dict]:
        """Fallback Kapruka CRM users if LLM generation fails."""
        base_users = [
            {
                "full_name": "Anushka Perera",
                "email": "anushka.perera@example.com",
                "phone": "0771234567",
                "district": "Colombo",
                "notes": "Registered Kapruka gift concierge user",
            },
            {
                "full_name": "Kamal Jayasuriya",
                "email": "kamal.jayasuriya@example.com",
                "phone": "0712345678",
                "district": "Kandy",
                "notes": "Registered Kapruka gift concierge user",
            },
            {
                "full_name": "Fathima Rahman",
                "email": "fathima.rahman@example.com",
                "phone": "0763456789",
                "district": "Gampaha",
                "notes": "Registered Kapruka gift concierge user",
            },
            {
                "full_name": "Arjun Sivarajah",
                "email": "arjun.sivarajah@example.com",
                "phone": "0754567890",
                "district": "Jaffna",
                "notes": "Registered Kapruka gift concierge user",
            },
            {
                "full_name": "Nethmi Wijesinghe",
                "email": "nethmi.wijesinghe@example.com",
                "phone": "0705678901",
                "district": "Galle",
                "notes": "Registered Kapruka gift concierge user",
            },
        ]

        users = []
        for i in range(n):
            user = dict(base_users[i % len(base_users)])
            if i >= len(base_users):
                user["email"] = user["email"].replace("@", f"{i + 1}@")
                user["phone"] = f"07{(10000000 + i):08d}"[:10]
            users.append(user)

        return users

    def _fallback_memory_facts(self, n: int) -> List[Dict]:
        """Fallback semantic facts for mem_facts testing."""
        facts = [
            {
                "text": "User loves dark chocolate.",
                "score": 0.95,
                "tags": ["preference", "food", "chocolate"],
            },
            {
                "text": "User is allergic to nuts.",
                "score": 1.0,
                "tags": ["allergy", "safety"],
            },
            {
                "text": "User prefers gifts under Rs. 5000.",
                "score": 0.9,
                "tags": ["budget", "preference"],
            },
            {
                "text": "User prefers flower bouquets for special occasions.",
                "score": 0.85,
                "tags": ["preference", "flowers", "occasion"],
            },
            {
                "text": "User usually requests delivery to Colombo.",
                "score": 0.8,
                "tags": ["delivery", "district"],
            },
        ]

        return [facts[i % len(facts)] for i in range(n)]

    def _fallback_gift_queries(self, n: int) -> List[str]:
        """Fallback user messages for router testing."""
        queries = [
            "I love dark chocolate but I cannot eat nuts.",
            "Find a birthday cake under Rs. 5000 for delivery to Kandy.",
            "Can this be delivered to Galle tomorrow?",
            "I prefer flowers and simple gift baskets.",
            "Show me premium chocolate gifts that are currently available.",
        ]

        return [queries[i % len(queries)] for i in range(n)]


def get_data_generator():
    """
    Get singleton Kapruka data generator instance.

    Returns:
        KaprukaDataGenerator with LLM.
    """
    from infrastructure.llm import get_chat_llm

    llm = get_chat_llm()
    return KaprukaDataGenerator(llm)
