from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, List, Sequence, Tuple

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from ...models import Department, Employee, Role


@dataclass(frozen=True)
class SeedConfig:
    employees: int = 60_000
    departments: int = 25
    levels: int = 5
    roles: int = 10
    seed: int = 42
    batch_size: int = 5_000
    truncate: bool = False


class Command(BaseCommand):
    help = "Seed PostgreSQL database with roles, a 5-level department tree, and employees."

    def add_arguments(self, parser):
        parser.add_argument("--employees", type=int, default=60_000)
        parser.add_argument("--departments", type=int, default=25)
        parser.add_argument("--levels", type=int, default=5)
        parser.add_argument("--roles", type=int, default=10)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--batch-size", type=int, default=5_000)
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Truncate Role/Department/Employee tables before seeding (fast reset).",
        )

    def handle(self, *args, **options):
        cfg = SeedConfig(
            employees=_require_positive_int(options["employees"], "employees"),
            departments=_require_positive_int(options["departments"], "departments"),
            levels=_require_positive_int(options["levels"], "levels"),
            roles=_require_positive_int(options["roles"], "roles"),
            seed=int(options["seed"]),
            batch_size=_require_positive_int(options["batch_size"], "batch_size"),
            truncate=bool(options["truncate"]),
        )

        if cfg.levels != 5:
            raise ValueError("This seeder must create a department tree with exactly 5 levels (--levels=5).")
        if cfg.departments != 25:
            raise ValueError("This seeder must create exactly 25 departments (--departments=25).")

        rnd = random.Random(cfg.seed)

        with transaction.atomic():
            if cfg.truncate:
                _truncate_tables([Employee, Department, Role])

            roles = _ensure_roles(cfg, rnd)
            departments = _ensure_department_tree(cfg, rnd)
            _seed_employees(cfg, rnd, roles, departments)

        self.stdout.write(self.style.SUCCESS("Seeding completed successfully."))


def _require_positive_int(value: int, name: str) -> int:
    """Fail-fast validation for positive integers."""
    try:
        iv = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer.")
    if iv <= 0:
        raise ValueError(f"{name} must be > 0.")
    return iv


def _truncate_tables(models: Sequence[type]) -> None:
    """
    TRUNCATE tables in dependency-safe order with CASCADE.

    PostgreSQL TRUNCATE is fast and resets identity sequences.
    """
    table_names = [m._meta.db_table for m in models]
    sql = "TRUNCATE TABLE {} RESTART IDENTITY CASCADE;".format(
        ", ".join(connection.ops.quote_name(t) for t in table_names)
    )
    with connection.cursor() as cursor:
        cursor.execute(sql)


def _ensure_roles(cfg: SeedConfig, rnd: random.Random) -> List[Role]:
    """Create roles if none exist (or if truncated). Returns all roles to use."""
    existing = list(Role.objects.all().only("id", "default_salary"))
    if existing:
        return existing

    role_names = [
        "Junior Developer",
        "Developer",
        "Senior Developer",
        "Tech Lead",
        "QA Engineer",
        "DevOps Engineer",
        "Product Manager",
        "Data Analyst",
        "HR Specialist",
        "Accountant",
        "Designer",
        "Support Engineer",
    ]
    rnd.shuffle(role_names)
    selected = role_names[: cfg.roles] if cfg.roles <= len(role_names) else None

    roles_to_create: List[Role] = []
    for i in range(cfg.roles):
        name = selected[i] if selected else f"Role {i + 1}"
        default_salary = rnd.randint(50_000, 140_000)
        roles_to_create.append(Role(name=name, default_salary=default_salary))

    Role.objects.bulk_create(roles_to_create, batch_size=cfg.batch_size)
    return list(Role.objects.all().only("id", "default_salary"))


def _ensure_department_tree(cfg: SeedConfig, rnd: random.Random) -> List[Department]:
    """Create a 5-level department tree with exactly 25 departments, or reuse existing."""
    existing_count = Department.objects.count()
    if existing_count >= cfg.departments:
        return list(Department.objects.all().only("id", "parent_id")[: cfg.departments])

    if existing_count != 0:
        raise RuntimeError(
            f"Department table already has {existing_count} rows. "
            f"Use --truncate to reset before seeding, or clear departments manually."
        )

    counts = [1, 3, 5, 7, 9]

    created: List[Department] = []
    parents: List[Department] = []

    roots = [Department(parent=None)]
    Department.objects.bulk_create(roots, batch_size=cfg.batch_size)
    parents = list(Department.objects.all().only("id", "parent_id"))
    created.extend(parents)

    prev_level_nodes = parents[: counts[0]]  
    start_level_index = 1

    for level in range(2, cfg.levels + 1):
        level_count = counts[level - 1]
        if not prev_level_nodes:
            raise RuntimeError("Invalid department tree generation: previous level is empty.")

        to_create: List[Department] = []
        for i in range(level_count):
            parent = prev_level_nodes[i % len(prev_level_nodes)]
            to_create.append(Department(parent_id=parent.id))

        Department.objects.bulk_create(to_create, batch_size=cfg.batch_size)

        total_expected = sum(counts[:level])
        current_all = list(Department.objects.all().only("id", "parent_id").order_by("id")[:total_expected])
        current_level_nodes = current_all[sum(counts[: level - 1]) : total_expected]

        created = current_all
        prev_level_nodes = current_level_nodes
        start_level_index += 1

    if len(created) != cfg.departments:
        raise RuntimeError(f"Department creation mismatch: expected {cfg.departments}, got {len(created)}")

    return created


def _seed_employees(
    cfg: SeedConfig,
    rnd: random.Random,
    roles: Sequence[Role],
    departments: Sequence[Department],
) -> None:
    """Bulk-create employees distributed across departments."""
    if not roles:
        raise RuntimeError("No roles available for employee generation.")
    if not departments:
        raise RuntimeError("No departments available for employee generation.")

    first_names = [
        "Данил", "Иван", "Глеб", "Святослав", "Петр", "Николай", "Августин", 
        "Икакий", "Александр", "Матвей"
    ]
    last_names = [
        "Федоров", "Якимов", "Петров", "Сапожников", "Курдюмов", "Хлебников", 
        "Исаев", "Пушкарев"
    ]

    middle_names = [
        "Евгеньевич", "Сергеевич", "Александрович", "Иванович", "Глебович",
        "Святославович", "Николаевич", "Августинович"
    ]
    role_ids_defaults: List[Tuple[int, int]] = [(r.id, r.default_salary) for r in roles]
    dept_ids: List[int] = [d.id for d in departments]

    now = timezone.now()
    total = cfg.employees
    batch_size = cfg.batch_size

    existing_count = Employee.objects.count()
    if existing_count != 0:
        raise RuntimeError(
            f"Employee table already has {existing_count} rows. "
            f"Use --truncate to reset before seeding, or clear employees manually."
        )

    created = 0
    dept_count = len(dept_ids)

    while created < total:
        remaining = total - created
        n = batch_size if remaining > batch_size else remaining

        employees_batch: List[Employee] = []
        employees_batch_extend = employees_batch.append

        for i in range(n):
            dept_id = dept_ids[(created + i) % dept_count]

            role_id, default_salary = role_ids_defaults[rnd.randrange(len(role_ids_defaults))]

            salary = default_salary + rnd.randint(0, 120_000)

            fn = first_names[rnd.randrange(len(first_names))]
            ln = last_names[rnd.randrange(len(last_names))]
            mn = middle_names[rnd.randrange(len(middle_names))]
            full_name = f"{fn} {ln} {mn} #{created + i + 1}"

            days_back = rnd.randint(0, 3650)
            seconds_back = rnd.randint(0, 24 * 3600 - 1)
            employment_date = now - timedelta(days=days_back, seconds=seconds_back)

            employees_batch_extend(
                Employee(
                    full_name=full_name,
                    role_id=role_id,
                    employment_date=employment_date,
                    salary=salary,
                    department_id=dept_id,
                )
            )

        Employee.objects.bulk_create(employees_batch, batch_size=cfg.batch_size)
        created += n
