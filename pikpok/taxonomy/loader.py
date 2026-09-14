"""Load the taxonomy YAML into structured Python objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainDef:
    """A single domain with its subdomains."""

    id: str
    name: str
    subdomains: dict[str, str]  # subdomain_id → display name


@dataclass(frozen=True)
class Taxonomy:
    """The complete, parsed taxonomy for one version."""

    version: str
    domains: dict[str, DomainDef]  # domain_id → DomainDef
    skills: dict[str, str]  # skill_id → display name
    puzzle_families: dict[str, str]  # family_id → display name

    # Convenience sets for fast lookup
    domain_ids: frozenset[str] = field(default=frozenset(), repr=False)
    skill_ids: frozenset[str] = field(default=frozenset(), repr=False)
    puzzle_family_ids: frozenset[str] = field(default=frozenset(), repr=False)

    def __post_init__(self) -> None:
        # frozen=True → use object.__setattr__ for init-time computation
        object.__setattr__(self, "domain_ids", frozenset(self.domains.keys()))
        object.__setattr__(self, "skill_ids", frozenset(self.skills.keys()))
        object.__setattr__(
            self, "puzzle_family_ids", frozenset(self.puzzle_families.keys())
        )

    def subdomain_ids_for(self, domain_id: str) -> frozenset[str]:
        """Return valid subdomain IDs for a given domain."""
        domain = self.domains.get(domain_id)
        if domain is None:
            return frozenset()
        return frozenset(domain.subdomains.keys())

    def is_valid_subdomain(self, domain_id: str, subdomain_id: str) -> bool:
        """Check if a subdomain belongs to the given domain."""
        return subdomain_id in self.subdomain_ids_for(domain_id)

    def domains_for_subdomain(self, subdomain_id: str) -> tuple[str, ...]:
        """Return the top-level domains that contain ``subdomain_id``.

        Subdomain IDs are not globally required to be unique (for example,
        ``recursion`` is used by both Algorithms and Programming), so the
        result is a tuple rather than a single parent domain.
        """
        return tuple(
            domain_id
            for domain_id, domain in self.domains.items()
            if subdomain_id in domain.subdomains
        )

    def all_subdomains(self) -> dict[str, str]:
        """Return every subdomain ID mapped to its display name."""
        return {
            subdomain_id: subdomain_name
            for domain in self.domains.values()
            for subdomain_id, subdomain_name in domain.subdomains.items()
        }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_TAXONOMY_PATH = Path(__file__).parent / "taxonomy.yaml"


def load_taxonomy(
    path: Path | str | None = None,
    *,
    expected_version: str | None = None,
) -> Taxonomy:
    """Load a taxonomy YAML file and return a ``Taxonomy`` instance.

    Parameters
    ----------
    path:
        Path to the YAML file.  Defaults to the bundled ``taxonomy.yaml``.
    expected_version:
        If given, raise ``ValueError`` when the file version does not match.
    """
    path = Path(path) if path is not None else _DEFAULT_TAXONOMY_PATH

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    version: str = raw["version"]
    if expected_version is not None and version != expected_version:
        raise ValueError(
            f"Taxonomy version mismatch: expected {expected_version}, "
            f"got {version}"
        )

    # Parse domains
    domains: dict[str, DomainDef] = {}
    for domain_id, domain_data in raw.get("domains", {}).items():
        subdomains = domain_data.get("subdomains", {})
        domains[domain_id] = DomainDef(
            id=domain_id,
            name=domain_data["name"],
            subdomains=dict(subdomains),
        )

    skills: dict[str, str] = dict(raw.get("skills", {}))
    puzzle_families: dict[str, str] = dict(raw.get("puzzle_families", {}))

    return Taxonomy(
        version=version,
        domains=domains,
        skills=skills,
        puzzle_families=puzzle_families,
    )


def taxonomy_to_prompt_block(taxonomy: Taxonomy) -> str:
    """Format the taxonomy as a text block suitable for inclusion in a VLM prompt."""
    lines: list[str] = []
    lines.append(f"TAXONOMY VERSION: {taxonomy.version}")
    lines.append("")

    lines.append(
        "APPROVED TOP-LEVEL DOMAIN IDS "
        "(valid for primary_domain and secondary_domains):"
    )
    for domain_id, domain_def in taxonomy.domains.items():
        lines.append(f"  - {domain_id}: {domain_def.name}")
    lines.append("")

    lines.append("APPROVED SUBDOMAIN IDS (valid only for subdomain):")
    for domain_id, domain_def in taxonomy.domains.items():
        lines.append(f"  {domain_id}:")
        for sub_id, sub_name in domain_def.subdomains.items():
            lines.append(f"    - {sub_id}: {sub_name}")
    lines.append("")

    lines.append("APPROVED PUZZLE FAMILIES:")
    for fam_id, fam_name in taxonomy.puzzle_families.items():
        lines.append(f"  - {fam_id}: {fam_name}")
    lines.append("")

    lines.append("APPROVED SKILLS:")
    for skill_id, skill_name in taxonomy.skills.items():
        lines.append(f"  - {skill_id}: {skill_name}")

    return "\n".join(lines)
